"""Geofence and occupancy checks.

The map fixtures here are deliberately **asymmetric**. A symmetric map hides
row-flip bugs — world y increases upward, PGM row 0 is the top — and that bug
mirrors every obstacle without failing a single symmetric test.
"""

from __future__ import annotations

import pytest

from cropwatcher.safety.geofence import Geofence, GeofenceViolation
from cropwatcher.safety.occupancy import (
    MapLoadError,
    ObstacleViolation,
    OccupancyGrid,
    bresenham,
)


class TestGeofence:
    def test_accepts_a_point_inside(self):
        fence = Geofence.square(1.0)
        assert fence.contains(0.0, 0.0, 0.5)
        fence.check(0.0, 0.0, 0.5)

    def test_rejects_beyond_each_axis(self):
        fence = Geofence.square(1.0)
        for x, y, z, axis in [
            (2.0, 0.0, 0.5, "x"),
            (0.0, -2.0, 0.5, "y"),
            (0.0, 0.0, 5.0, "z"),
        ]:
            with pytest.raises(GeofenceViolation, match=f"^{axis}="):
                fence.check(x, y, z)

    def test_boundary_is_inclusive(self):
        fence = Geofence(x_min=-1, x_max=1, y_min=-1, y_max=1, z_min=0.1, z_max=2.0)
        fence.check(1.0, 1.0, 2.0)
        fence.check(-1.0, -1.0, 0.1)

    def test_floor_is_not_a_valid_target(self):
        """z_min sits above zero: nothing should be asked to fly at floor level."""
        with pytest.raises(GeofenceViolation, match="^z="):
            Geofence.square(1.0).check(0.0, 0.0, 0.0)

    def test_message_names_the_axis_and_the_bound(self):
        """The dashboard shows this verbatim, so it has to be useful."""
        with pytest.raises(GeofenceViolation) as e:
            Geofence.square(1.0).check(3.5, 0.0, 0.5)
        assert "x=+3.50" in str(e.value)
        assert "-1.00" in str(e.value) and "+1.00" in str(e.value)

    def test_inverted_bounds_are_rejected_at_construction(self):
        with pytest.raises(ValueError, match="inverted or empty"):
            Geofence(x_min=1, x_max=-1, y_min=-1, y_max=1)

    def test_clamp_returns_nearest_inside_point(self):
        fence = Geofence.square(1.0)
        assert fence.clamp(5.0, -5.0, 9.0) == (1.0, -1.0, 2.0)


class TestBresenham:
    def test_includes_both_endpoints(self):
        line = bresenham(0, 0, 3, 0)
        assert line[0] == (0, 0)
        assert line[-1] == (3, 0)

    def test_horizontal_line_is_contiguous(self):
        assert bresenham(0, 2, 4, 2) == [(0, 2), (1, 2), (2, 2), (3, 2), (4, 2)]

    def test_diagonal_steps_once_per_cell(self):
        assert bresenham(0, 0, 3, 3) == [(0, 0), (1, 1), (2, 2), (3, 3)]

    def test_works_in_every_direction(self):
        for end in [(3, 1), (-3, 1), (3, -1), (-3, -1)]:
            line = bresenham(0, 0, *end)
            assert line[0] == (0, 0)
            assert line[-1] == end

    def test_single_point(self):
        assert bresenham(2, 2, 2, 2) == [(2, 2)]


def write_map(tmp_path, rows: list[str], resolution=1.0, origin=(0.0, 0.0)):
    """Build a PGM + YAML pair. '#' is a wall, '.' is free.

    Row 0 of `rows` is the TOP of the image, which is HIGH y in world space.
    """
    height = len(rows)
    width = len(rows[0])
    pixels = bytearray()
    for row in rows:
        for ch in row:
            pixels.append(0 if ch == "#" else 255)   # black occupied, white free

    pgm = tmp_path / "map.pgm"
    pgm.write_bytes(b"P5\n%d %d\n255\n" % (width, height) + bytes(pixels))

    yaml = tmp_path / "map.yaml"
    yaml.write_text(
        f"image: map.pgm\n"
        f"resolution: {resolution}\n"
        f"origin: [{origin[0]}, {origin[1]}, 0.0]\n"
        f"negate: 0\n"
        f"occupied_thresh: 0.65\n"
        f"free_thresh: 0.196\n"
    )
    return yaml


class TestOccupancyGrid:
    def test_loads_a_map(self, tmp_path):
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, ["...", "...", "..."]))
        assert grid.width == 3
        assert grid.height == 3

    def test_free_cells_are_not_blocked(self, tmp_path):
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, ["...", "...", "..."]))
        assert not grid.is_blocked(1.5, 1.5)

    def test_occupied_cells_are_blocked(self, tmp_path):
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, ["###", "###", "###"]))
        assert grid.is_blocked(1.5, 1.5)

    def test_row_flip_is_correct(self, tmp_path):
        """The asymmetric case. A wall drawn along the TOP image row must be
        found at HIGH world y, not low. Getting this backwards mirrors the map
        and no symmetric fixture would catch it."""
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, [
            "###",   # image row 0 -> world y 2..3  (high)
            "...",
            "...",   # image row 2 -> world y 0..1  (low)
        ]))
        assert grid.is_blocked(1.5, 2.5)        # high y: the wall
        assert not grid.is_blocked(1.5, 0.5)    # low y: clear

    def test_off_map_counts_as_blocked(self, tmp_path):
        """Unmapped is not 'probably fine'."""
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, ["...", "...", "..."]))
        assert grid.is_blocked(99.0, 99.0)
        assert grid.is_blocked(-5.0, 0.5)

    def test_origin_offset_is_applied(self, tmp_path):
        grid = OccupancyGrid.from_yaml(
            write_map(tmp_path, ["###", "...", "..."], origin=(-1.5, -1.5))
        )
        # With the origin shifted, world (0,0) is the middle cell, which is free.
        assert not grid.is_blocked(0.0, 0.0)

    def test_resolution_is_applied(self, tmp_path):
        grid = OccupancyGrid.from_yaml(
            write_map(tmp_path, ["..#", "...", "..."], resolution=0.5)
        )
        # 0.5 m cells: the blocked cell spans x 1.0-1.5, y 1.0-1.5.
        assert grid.is_blocked(1.25, 1.25)
        assert not grid.is_blocked(0.25, 0.25)


class TestPathChecking:
    def test_clear_path_passes(self, tmp_path):
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, ["....."] * 5))
        assert grid.path_is_clear(0.5, 0.5, 4.5, 4.5)
        grid.check_path(0.5, 0.5, 4.5, 4.5)

    def test_wall_between_two_clear_points_is_found(self, tmp_path):
        """Both endpoints are free; the line between them is not. This is the
        whole reason for a line check rather than per-waypoint checks."""
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, [
            ".....",
            ".....",
            "#####",   # wall across the middle
            ".....",
            ".....",
        ]))
        assert not grid.is_blocked(2.5, 0.5)     # start free
        assert not grid.is_blocked(2.5, 4.5)     # end free
        assert not grid.path_is_clear(2.5, 0.5, 2.5, 4.5)

        with pytest.raises(ObstacleViolation, match="crosses a blocked"):
            grid.check_path(2.5, 0.5, 2.5, 4.5)

    def test_path_around_a_wall_is_clear(self, tmp_path):
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, [
            ".....",
            ".....",
            "###..",   # wall stops short of the right edge
            ".....",
            ".....",
        ]))
        assert grid.path_is_clear(4.5, 0.5, 4.5, 4.5)

    def test_path_leaving_the_map_is_rejected(self, tmp_path):
        grid = OccupancyGrid.from_yaml(write_map(tmp_path, ["..."] * 3))
        assert not grid.path_is_clear(1.5, 1.5, 50.0, 50.0)


class TestMapLoadErrors:
    def test_missing_yaml(self, tmp_path):
        with pytest.raises(MapLoadError, match="not found"):
            OccupancyGrid.from_yaml(tmp_path / "nope.yaml")

    def test_missing_image(self, tmp_path):
        yaml = tmp_path / "map.yaml"
        yaml.write_text("image: gone.pgm\nresolution: 1.0\norigin: [0,0,0]\n")
        with pytest.raises(MapLoadError, match="image not found"):
            OccupancyGrid.from_yaml(yaml)

    def test_missing_resolution(self, tmp_path):
        write_map(tmp_path, ["..."])
        yaml = tmp_path / "map.yaml"
        yaml.write_text("image: map.pgm\norigin: [0,0,0]\n")
        with pytest.raises(MapLoadError, match="resolution"):
            OccupancyGrid.from_yaml(yaml)

    def test_truncated_image(self, tmp_path):
        (tmp_path / "map.pgm").write_bytes(b"P5\n10 10\n255\n" + bytes(5))
        yaml = tmp_path / "map.yaml"
        yaml.write_text("image: map.pgm\nresolution: 1.0\norigin: [0,0,0]\n")
        with pytest.raises(MapLoadError, match="expected 100 pixels"):
            OccupancyGrid.from_yaml(yaml)

    def test_not_a_pgm(self, tmp_path):
        (tmp_path / "map.pgm").write_bytes(b"GIF89a")
        yaml = tmp_path / "map.yaml"
        yaml.write_text("image: map.pgm\nresolution: 1.0\norigin: [0,0,0]\n")
        with pytest.raises(MapLoadError, match="not a PGM"):
            OccupancyGrid.from_yaml(yaml)

    def test_pgm_comments_are_skipped(self, tmp_path):
        """GIMP writes a comment line into every PGM it exports."""
        (tmp_path / "map.pgm").write_bytes(
            b"P5\n# Created by GIMP\n2 2\n255\n" + bytes([255, 255, 255, 255])
        )
        yaml = tmp_path / "map.yaml"
        yaml.write_text("image: map.pgm\nresolution: 1.0\norigin: [0,0,0]\n")
        grid = OccupancyGrid.from_yaml(yaml)
        assert grid.width == 2 and grid.height == 2
