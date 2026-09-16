"""Static obstacle checking against an occupancy grid.

Loads the ROS ``map_server`` format — a YAML descriptor beside a PGM image —
because that is what the greenhouse was mapped with, and keeping the format
means existing maps still work.

**This is a static check.** It knows about walls and benches that were there
when the map was made. It does not see a person, a trolley, or a plant that
grew. The operator remains responsible for looking at the actual room; a route
the software accepts is not thereby safe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ROS convention: cells at or above this are obstacles, below `free_thresh` are
# clear, and the band between is unknown.
DEFAULT_OCCUPIED_THRESHOLD = 65


class ObstacleViolation(ValueError):
    """A waypoint or path crosses a blocked cell."""


class MapLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class MapMetadata:
    resolution: float           # metres per cell
    origin_x: float             # world coords of cell (0, 0)
    origin_y: float
    negate: bool
    occupied_thresh: float
    free_thresh: float


class OccupancyGrid:
    """A static map, in world coordinates.

    Cell values are 0-100 ROS-style: 0 free, 100 occupied, -1 unknown.
    """

    def __init__(
        self,
        cells: list[list[int]],
        metadata: MapMetadata,
        occupied_threshold: int = DEFAULT_OCCUPIED_THRESHOLD,
    ) -> None:
        self.cells = cells
        self.metadata = metadata
        self.occupied_threshold = occupied_threshold
        self.height = len(cells)
        self.width = len(cells[0]) if cells else 0

    # ── loading ──────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, yaml_path: Path | str, **kwargs) -> OccupancyGrid:
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise MapLoadError(f"map descriptor not found: {yaml_path}")

        meta, image_name = _parse_map_yaml(yaml_path)
        image_path = yaml_path.parent / image_name
        if not image_path.exists():
            raise MapLoadError(f"map image not found: {image_path}")

        cells = _load_pgm_as_occupancy(image_path, meta)
        log.info("loaded map %s (%dx%d at %.3f m/cell)",
                 yaml_path.name, len(cells[0]), len(cells), meta.resolution)
        return cls(cells, meta, **kwargs)

    # ── coordinate transforms ────────────────────────────────────────────

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """World metres to (column, row).

        Rows are flipped: image row 0 is the *top*, but map origin is the
        bottom-left corner. Getting this backwards mirrors the map vertically,
        which passes every test that uses a symmetric fixture — so the tests
        use an asymmetric one.
        """
        res = self.metadata.resolution
        col = int((x - self.metadata.origin_x) / res)
        row = self.height - 1 - int((y - self.metadata.origin_y) / res)
        return col, row

    def in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.width and 0 <= row < self.height

    def value_at(self, x: float, y: float) -> int:
        """Occupancy at a world point. Outside the map counts as unknown."""
        col, row = self.world_to_cell(x, y)
        if not self.in_bounds(col, row):
            return -1
        return self.cells[row][col]

    # ── checks ───────────────────────────────────────────────────────────

    def is_blocked(self, x: float, y: float) -> bool:
        """Treat unknown as blocked. Off-map or unmapped is not 'probably fine'."""
        value = self.value_at(x, y)
        return value < 0 or value >= self.occupied_threshold

    def path_is_clear(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        """Whether a straight line between two world points crosses anything."""
        start = self.world_to_cell(x0, y0)
        end = self.world_to_cell(x1, y1)
        for col, row in bresenham(*start, *end):
            if not self.in_bounds(col, row):
                return False
            value = self.cells[row][col]
            if value < 0 or value >= self.occupied_threshold:
                return False
        return True

    def check_path(self, x0: float, y0: float, x1: float, y1: float) -> None:
        if not self.path_is_clear(x0, y0, x1, y1):
            raise ObstacleViolation(
                f"path ({x0:+.2f}, {y0:+.2f}) -> ({x1:+.2f}, {y1:+.2f}) "
                f"crosses a blocked or unmapped cell"
            )


def bresenham(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Every cell a straight line passes through, endpoints included.

    Integer-only, so there is no floating-point drift on long lines.
    """
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            return points
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy


# ── map file parsing ─────────────────────────────────────────────────────


def _parse_map_yaml(path: Path) -> tuple[MapMetadata, str]:
    """Minimal parser for the map_server YAML subset.

    Hand-rolled rather than adding a YAML dependency to the flight agent: the
    format is five scalars and one list, and every dependency here has to be
    bundled into the desktop installer.
    """
    text = path.read_text(encoding="utf-8")

    def scalar(key: str, default: str | None = None) -> str:
        match = re.search(rf"^\s*{key}\s*:\s*(.+?)\s*$", text, re.MULTILINE)
        if match is None:
            if default is None:
                raise MapLoadError(f"'{key}' missing from {path.name}")
            return default
        return match.group(1).strip().strip("'\"")

    origin_raw = scalar("origin")
    numbers = re.findall(r"-?\d+\.?\d*", origin_raw)
    if len(numbers) < 2:
        raise MapLoadError(f"could not parse origin from {origin_raw!r}")

    return (
        MapMetadata(
            resolution=float(scalar("resolution")),
            origin_x=float(numbers[0]),
            origin_y=float(numbers[1]),
            negate=scalar("negate", "0").strip() in {"1", "true", "True"},
            occupied_thresh=float(scalar("occupied_thresh", "0.65")),
            free_thresh=float(scalar("free_thresh", "0.196")),
        ),
        scalar("image"),
    )


def _load_pgm_as_occupancy(path: Path, meta: MapMetadata) -> list[list[int]]:
    """Read a binary or ASCII PGM into 0-100 occupancy values."""
    data = path.read_bytes()
    magic, width, height, maxval, pixel_start = _read_pgm_header(data)

    if magic == b"P5":
        pixels = list(data[pixel_start:pixel_start + width * height])
    else:  # P2, ASCII
        tokens = data[pixel_start:].split()
        pixels = [int(t) for t in tokens[: width * height]]

    if len(pixels) < width * height:
        raise MapLoadError(
            f"{path.name}: expected {width * height} pixels, found {len(pixels)}"
        )

    cells: list[list[int]] = []
    for row in range(height):
        out_row: list[int] = []
        for col in range(width):
            value = pixels[row * width + col]
            # map_server: white is free, black is occupied, unless negated.
            occupancy = value / maxval if meta.negate else (maxval - value) / maxval
            if occupancy >= meta.occupied_thresh:
                out_row.append(100)
            elif occupancy <= meta.free_thresh:
                out_row.append(0)
            else:
                out_row.append(-1)          # unknown
        cells.append(out_row)
    return cells


def _read_pgm_header(data: bytes) -> tuple[bytes, int, int, int, int]:
    """Return (magic, width, height, maxval, offset of first pixel)."""
    if data[:2] not in (b"P5", b"P2"):
        raise MapLoadError(f"not a PGM file (magic {data[:2]!r})")

    magic = data[:2]
    fields: list[int] = []
    i = 2
    while len(fields) < 3:
        while i < len(data) and data[i : i + 1].isspace():
            i += 1
        if data[i : i + 1] == b"#":                   # comment to end of line
            while i < len(data) and data[i : i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < len(data) and not data[i : i + 1].isspace():
            i += 1
        fields.append(int(data[start:i]))

    return magic, fields[0], fields[1], fields[2], i + 1
