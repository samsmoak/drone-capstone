"""Where the drone's position can be trusted — a room's Lighthouse COVERAGE.

The drone senses no walls (it carries no distance sensor). What the Lighthouse
system establishes is where the drone KNOWS where it is: wherever enough base
stations' sweeps reach its deck. That is the space a mission can fly in, and
Room.coverage is its outline (floorplan.py; validate.py's outer bound).

TWO WAYS TO KNOW IT

  PREDICTED  from the base stations' poses (the geometry `cropwatcher
             geometry` measures and stores on the drone) and their field of
             view: a point is covered when enough stations see it (stations_needed:
             one by default, as the project flies). A
             prediction — shown to guide the survey, never flown on.
  MEASURED   the SURVEY: the operator carries the drone around the room while
             the agent keeps every position at which enough stations were
             received. Their outline is Room.coverage. This is what flies.

WHY AN OUTLINE AND A HEIGHT BAND IS ENOUGH. What one station sees is a
pyramid (its field of view) — convex. Two stations' overlap, within a height
band, is the intersection of convex shapes, so it is convex too, and its
outline is the convex hull of the covered points. (What it cannot show: a
cabinet shading part of the room. The survey finds those — a walked edge
stops where reception does.)

THE BASE STATION'S FRAME (cflib lighthouse_bs_vector.from_cart): x forward
out of the station, y to its left, z up; a geometry's rotation matrix turns
the station's frame into the room's.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from cropwatcher.mission.plan.geofence import MAX_VERTICES, Geofence
from cropwatcher.mission.plan.shapes import Point, cross, signed_area

#: Valve's published field of view for SteamVR Base Station 2.0 (the lab's
#: HTC VIVE 2QCJ100): 150° wide, 110° tall — half-angles from its forward axis.
FOV_HALF_H_DEG = 75.0
FOV_HALF_V_DEG = 55.0
#: A reach beyond which a prediction does not count a station. NOT MEASURED in
#: this lab: Bitcraze sizes a two-station Lighthouse 2 system for a room a few
#: metres across. The survey is the measurement; this only bounds a guess.
MAX_RANGE_M = 6.0
#: The prediction's grid.
GRID_M = 0.10
def stations_needed(override: int | None = None) -> int:
    """How many stations must see a spot for it to count: the project's own
    policy (safety/flight_guard.py required_stations — ONE by default, as the
    lab has flown on one; two with CROPWATCHER_MIN_STATIONS=2). This was a
    fixed 2 until 2026-10-01, which made the survey count nothing in a
    one-station room."""
    if override is not None:
        return override
    from cropwatcher.safety.flight_guard import required_stations
    return required_stations()


@dataclass(frozen=True)
class StationPose:
    """One base station: where it is and which way it faces, in room metres."""

    origin: tuple[float, float, float]
    #: Rows of the 3x3 matrix turning the station's frame into the room's.
    rotation: tuple[tuple[float, float, float], ...]

    def sees(self, p: tuple[float, float, float]) -> bool:
        d = (p[0] - self.origin[0], p[1] - self.origin[1], p[2] - self.origin[2])
        if math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) > MAX_RANGE_M:
            return False
        r = self.rotation
        # The room's vector in the station's frame: the matrix's transpose.
        fx = r[0][0] * d[0] + r[1][0] * d[1] + r[2][0] * d[2]
        fy = r[0][1] * d[0] + r[1][1] * d[1] + r[2][1] * d[2]
        fz = r[0][2] * d[0] + r[1][2] * d[1] + r[2][2] * d[2]
        if fx <= 0:
            return False                                  # behind the station
        return (abs(math.degrees(math.atan2(fy, fx))) <= FOV_HALF_H_DEG
                and abs(math.degrees(math.atan2(fz, fx))) <= FOV_HALF_V_DEG)


# ── outlines ─────────────────────────────────────────────────────────────


def convex_hull(points: Iterable[Point]) -> list[Point]:
    """Counter-clockwise hull, no repeated end point (Andrew's monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def simplify(hull: Sequence[Point], max_corners: int = MAX_VERTICES) -> list[Point]:
    """At most `max_corners` corners (a fence's limit), dropping the corner
    that adds the least area each time. On a convex outline that can only
    SHRINK it — the safe direction for a space the drone must stay inside."""
    out = list(hull)
    while len(out) > max_corners:
        areas = [abs(cross(out[i - 1], out[i], out[(i + 1) % len(out)]))
                 for i in range(len(out))]
        del out[areas.index(min(areas))]
    return out


def clip_to_convex(subject: Sequence[Point], clip: Sequence[Point]) -> list[Point]:
    """The part of `subject` inside the CONVEX polygon `clip` (Sutherland–
    Hodgman). Empty when they do not overlap."""
    if len(clip) < 3:
        return []
    ccw = signed_area(clip) > 0
    out = list(subject)
    for a, b in zip(clip, list(clip[1:]) + [clip[0]], strict=True):
        if not out:
            break
        inp, out = out, []

        def inside(p: Point, a: Point = a, b: Point = b) -> bool:
            c = cross(a, b, p)
            return c >= 0 if ccw else c <= 0

        for i, cur in enumerate(inp):
            prev = inp[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(_intersect(prev, cur, a, b))
                out.append(cur)
            elif inside(prev):
                out.append(_intersect(prev, cur, a, b))
    return out


def _intersect(p: Point, q: Point, a: Point, b: Point) -> Point:
    """Where segment p–q meets the line a–b (they are known to cross)."""
    x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
    x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-12:
        return q
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


# ── predicted ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Prediction:
    """The predicted coverage: its outline at every height in the band, and
    the part covered at ALL of them (what a mission can count on)."""

    z_min: float
    z_max: float
    #: (height, outline) per grid height, low to high. An outline may be empty.
    slices: tuple[tuple[float, tuple[Point, ...]], ...]
    #: Covered at every height of the band, as a fence; None when nowhere is.
    everywhere: Geofence | None

    def to_dict(self) -> dict[str, object]:
        return {
            "z_min_m": self.z_min, "z_max_m": self.z_max,
            "slices": [{"z_m": round(z, 3), "outline": [[round(x, 3), round(y, 3)] for x, y in o]}
                       for z, o in self.slices],
            "everywhere": self.everywhere.to_dict() if self.everywhere else None,
        }


def predict(stations: Sequence[StationPose], fence: Geofence, *,
            grid_m: float = GRID_M, min_stations: int | None = None) -> Prediction:
    """Which part of the room's fence (and its height band) the stations cover."""
    needed = stations_needed(min_stations)
    x0, y0, x1, y1 = fence.bounds()
    nx, ny = max(1, round((x1 - x0) / grid_m)), max(1, round((y1 - y0) / grid_m))
    heights = _band(fence.z_min, fence.z_max, grid_m)
    cells = [(x0 + (i + 0.5) * (x1 - x0) / nx, y0 + (j + 0.5) * (y1 - y0) / ny)
             for i in range(nx) for j in range(ny)]
    cells = [c for c in cells if fence.contains(*c)]
    slices: list[tuple[float, tuple[Point, ...]]] = []
    every: set[Point] | None = None
    for z in heights:
        covered = {c for c in cells
                   if sum(s.sees((c[0], c[1], z)) for s in stations) >= needed}
        slices.append((z, tuple(simplify(convex_hull(covered))) if len(covered) >= 3 else ()))
        every = covered if every is None else every & covered
    hull = simplify(convex_hull(every or ()))
    everywhere = (Geofence.polygon(hull, z_min=fence.z_min, z_max=fence.z_max)
                  if len(hull) >= 3 else None)
    return Prediction(fence.z_min, fence.z_max, tuple(slices), everywhere)


def _band(lo: float, hi: float, step: float) -> list[float]:
    n = max(1, round((hi - lo) / step))
    return [lo + k * (hi - lo) / n for k in range(n + 1)]


# ── measured: the survey ─────────────────────────────────────────────────


class Survey:
    """Positions the drone stood behind, while it is carried round the room.
    Plain data in, an outline out — no radio here.

    A reading counts only when enough stations were received AND the drone
    trusted its position (flight_guard.position_trusted, passed in as
    `trusted`). Received alone is not enough: on 2026-10-05 a survey taken
    before the station was measured counted every reading — the station's
    light was arriving — and saved the drifting estimate as the flyable
    space, an outline from -100 m to +100 m that moved every point."""

    def __init__(self, *, min_stations: int | None = None) -> None:
        self._min = stations_needed(min_stations)
        self.kept: list[tuple[float, float, float]] = []
        self.seen = 0

    def add(self, x: float, y: float, z: float, received_mask: int, *,
            trusted: bool = True) -> bool:
        """One telemetry sample. True when it counts (enough stations, and a
        position the drone stands behind)."""
        self.seen += 1
        if not trusted or not all(math.isfinite(v) for v in (x, y, z)):
            return False
        if bin(int(received_mask) & 0xFFFF).count("1") < self._min:
            return False
        self.kept.append((x, y, z))
        return True

    @property
    def spots(self) -> int:
        """Distinct places counted, GRID_M apart. Telemetry arrives at 10 Hz,
        so "171 positions" was 17 s of readings, not 171 places."""
        return len({(round(x / GRID_M), round(y / GRID_M)) for x, y, _ in self.kept})

    def outline(self) -> list[Point]:
        return convex_hull((round(x, 3), round(y, 3)) for x, y, _ in self.kept)

    def coverage(self, *, z_min: float, z_max: float) -> Geofence | None:
        """The measured coverage as a fence, in the room's own height band —
        the drone is carried at hand height, so the survey says where, not how
        high. None until it encloses an area."""
        hull = simplify(self.outline())
        if len(hull) < 3 or abs(signed_area(hull)) < 0.05:
            return None
        return Geofence.polygon(hull, z_min=z_min, z_max=z_max)
