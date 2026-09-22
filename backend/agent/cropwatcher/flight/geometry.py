"""Where the base stations are, measured from the floor of this room.

The drone works out its position by crossing the beams of two base stations.
To do that it needs to know where each station IS — its position and the way
it is pointing. That is the "geometry", and it is stored on the drone.

Geometry goes stale the moment a station is nudged, re-aimed, or moved to
another room, and stale geometry does not fail loudly: the two stations simply
disagree, and the estimate jumps between their answers. Measured in the lab on
2026-09-21, with both stations received 96 % of the time and the drone sitting
still on the floor: the position jumped 21 cm in a single 0.1 s step, wandering
33 cm in ten seconds. Nothing else in the system can recover from that — the
height hold, the guards and the geofence all read a position that is lying.

So this measures it again. It is Bitcraze's own procedure (the cflib example
`lighthouse/multi_bs_geometry_estimation.py`, which is what cfclient runs),
driven from our CLI so a lab session does not need cfclient installed:

    1. the drone at the ORIGIN         — where (0, 0, 0) should be
    2. the drone on the +X AXIS        — a measured distance away, which is
                                         what gives the system its scale
    3. several places in the XY PLANE  — the floor
    4. several places around the SPACE — including up in the air, by hand,
                                         because the drone flies up there

Then the solver finds the station poses that best explain every sample, and
the result is written to the drone, where it persists across a power cycle.

Read-only until the final write, and no motors ever spin: the drone is carried
by hand for every sample.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: How long to wait for a station's beams at one position before giving up.
SAMPLE_TIMEOUT_S = 20.0

#: Samples wanted at each stage. The floor and the space want several, spread
#: out: one sample says where the drone is, a spread of them says where the
#: STATIONS are.
XY_PLANE_SAMPLES = 4
SPACE_SAMPLES = 6


@dataclass
class GeometryStep:
    """One thing the person holding the drone is asked to do."""

    key: str
    instruction: str
    count: int = 1


@dataclass
class GeometryResult:
    converged: bool
    stations: dict[int, Any] = field(default_factory=dict)
    #: Mean and max error over the samples, in metres, as the solver reports.
    mean_error_m: float = 0.0
    max_error_m: float = 0.0
    message: str = ""
    written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "converged": self.converged,
            "stations": sorted(self.stations),
            "mean_error_m": round(self.mean_error_m, 4),
            "max_error_m": round(self.max_error_m, 4),
            "written": self.written,
            "message": self.message,
        }


def steps(reference_distance_m: float) -> list[GeometryStep]:
    """The order the samples are taken in, in the words the operator hears."""
    return [
        GeometryStep(
            "origin",
            "Put the drone where you want (0, 0, 0) to be — the middle of the "
            "flying area, on the floor, facing the direction you want to call "
            "forward.",
        ),
        GeometryStep(
            "x_axis",
            f"Move the drone {reference_distance_m:.2f} m straight forward, along "
            f"the direction it is facing, still on the floor. Measure this one: "
            f"it is what sets the scale of everything else.",
        ),
        GeometryStep(
            "xy_plane",
            "Put the drone somewhere else on the floor, anywhere in the flying "
            "area. Spread these out — corners are good.",
            XY_PLANE_SAMPLES,
        ),
        GeometryStep(
            "space",
            "Hold the drone up in the air, somewhere in the space it will fly "
            "in. Vary the height and the place each time; tilt it a little.",
            SPACE_SAMPLES,
        ),
    ]


class SweepAngles:
    """Averaged sweep angles at one position, read from the drone.

    Wraps cflib's reader so the caller waits for a sample instead of handling
    a callback, and so a position where the beams do not arrive fails with a
    sentence rather than hanging.
    """

    def __init__(self, cf: Any, *, timeout_s: float = SAMPLE_TIMEOUT_S) -> None:
        self._cf = cf
        self._timeout = timeout_s

    def record(self) -> Any:
        from threading import Event

        from cflib.localization import LighthouseSweepAngleAverageReader
        from cflib.localization.lighthouse_cf_pose_sample import LhCfPoseSample

        done = Event()
        captured: dict[str, Any] = {}

        def ready(angles: dict[int, tuple[int, Any]]) -> None:
            captured["angles"] = {bs: vectors for bs, (_, vectors) in angles.items()}
            done.set()

        reader = LighthouseSweepAngleAverageReader(self._cf, ready)
        reader.start_angle_collection()
        if not done.wait(self._timeout):
            raise TimeoutError(
                "No base station beams reached the drone here. Check both stations are "
                "powered and pointing this way, and that nothing is between them and "
                "the drone."
            )
        angles = captured["angles"]
        if len(angles) < 2:
            raise ValueError(
                f"Only base station {', '.join(str(b) for b in sorted(angles))} reached "
                f"the drone here. Two are needed at every position — move the drone, or "
                f"re-aim the station that is missing."
            )
        return LhCfPoseSample(angles_calibrated=angles)


def estimate(
    cf: Any,
    collect: Callable[[GeometryStep, int], Any],
    *,
    reference_distance_m: float = 1.0,
    write: bool = True,
) -> GeometryResult:
    """Walk the steps, solve, and — unless asked not to — write the result.

    `collect(step, index)` is the caller's business: it prompts whoever is
    holding the drone and returns one recorded sample. Keeping it out here is
    what lets this be tested without a drone or a person.
    """
    from cflib.localization import LhDeck4SensorPositions
    from cflib.localization.lighthouse_geo_estimation_manager import (
        LhGeoEstimationManager,
        LhGeoInputContainer,
    )

    container = LhGeoInputContainer(LhDeck4SensorPositions.positions)
    plan = steps(reference_distance_m)

    container.set_origin_sample(collect(plan[0], 0))
    container.set_x_axis_sample(collect(plan[1], 0))
    container.set_xy_plane_samples([collect(plan[2], i) for i in range(plan[2].count)])
    container.append_xyz_space_samples([collect(plan[3], i) for i in range(plan[3].count)])

    data = container.get_data_copy()
    solution = LhGeoEstimationManager.estimate_geometry(data)
    if not solution.has_converged:
        return GeometryResult(
            converged=False,
            message=(
                "The solver could not make sense of these samples: "
                f"{solution.progress_info or 'no further detail'}. Usually it means the "
                "samples were too close together, or a station moved during the "
                "measurement. Run it again, spreading the positions out."
            ),
        )
    LhGeoEstimationManager.align_and_scale_solution(
        data, solution, solution.samples, reference_distance_m)

    result = GeometryResult(
        converged=True,
        stations=dict(solution.bs_poses),
        mean_error_m=float(getattr(solution.error_stats, "mean", 0.0)),
        max_error_m=float(getattr(solution.error_stats, "max", 0.0)),
        message=f"Solved for base stations {', '.join(str(b) for b in sorted(solution.bs_poses))}.",
    )
    if write:
        result.written = _write(cf, solution.bs_poses)
    return result


def _write(cf: Any, poses: dict[int, Any]) -> bool:
    """Store the geometry on the drone, where it survives a power cycle."""
    from threading import Event

    from cflib.localization import LighthouseConfigWriter
    from cflib.localization.lighthouse_types import LighthouseBsGeometry

    geometry = {}
    for station, pose in poses.items():
        geo = LighthouseBsGeometry()
        geo.origin = pose.translation.tolist()
        geo.rotation_matrix = pose.rot_matrix.tolist()
        geo.valid = True
        geometry[station] = geo

    done = Event()
    LighthouseConfigWriter(cf).write_and_store_config(lambda *_: done.set(), geos=geometry)
    if not done.wait(10.0):
        log.warning("the drone did not confirm the new geometry")
        return False
    # The drone needs a moment before its estimate reflects the new geometry.
    time.sleep(0.5)
    return True
