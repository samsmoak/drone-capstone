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

#: How closely the two single-station samples must agree about where the
#: station is before the answer is trusted, in metres. The true pose and its
#: mirror land far apart — metres, usually — so this only has to be tighter
#: than that while staying loose enough for a hand-carried 1 m step.
SINGLE_STATION_AGREEMENT_M = 0.25


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

    def __init__(self, cf: Any, *, timeout_s: float = SAMPLE_TIMEOUT_S,
                 min_stations: int = 2) -> None:
        self._cf = cf
        self._timeout = timeout_s
        self._min_stations = min_stations

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
        if len(angles) < self._min_stations:
            raise ValueError(
                f"Only base station {', '.join(str(b) for b in sorted(angles))} reached "
                f"the drone here. {self._min_stations} are needed at every position — "
                f"move the drone, or re-aim the station that is missing."
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


# ── one base station ─────────────────────────────────────────────────────
#
# Lighthouse V2 can position from a single station, so a room with one is not
# a room with none. The solver above cannot be used for it: it works by
# crossing the views of station pairs, and with one station there is no pair.
#
# Instead the pose comes from IPPE — the deck's four photodiodes are a known
# planar target, and the angles they measure fix where the station must be.
# cflib does this per station already (LhCfPoseSample.augment_with_ippe) and
# hands back the station's pose in the DRONE's frame, so with the drone at the
# origin that is the room's frame too.
#
# THE CATCH, and the reason this is not just "take the first solution": IPPE
# returns TWO poses for a planar target, and for a target 3 cm across seen
# from metres away they reproject almost identically. The wrong one is a
# MIRROR — a room where forward is backward. Reprojection error alone picks it
# wrong often enough to matter, so a second sample, a measured distance away,
# decides between them: only the true pose puts the station in the same place
# from both.


def single_station_steps(reference_distance_m: float) -> list[GeometryStep]:
    return [
        GeometryStep(
            "origin",
            "Put the drone where you want (0, 0, 0) to be — on the floor, "
            "facing the direction you want to call forward. Keep the deck's "
            "view of the base station clear.",
        ),
        GeometryStep(
            "x_axis",
            f"Move the drone {reference_distance_m:.2f} m straight forward, "
            f"along the direction it is facing, still on the floor and still "
            f"facing the SAME way. Measure it: this one both sets the scale "
            f"and decides between two mirror-image answers.",
        ),
    ]


def estimate_single(
    cf: Any,
    collect: Callable[[GeometryStep, int], Any],
    *,
    reference_distance_m: float = 1.0,
    write: bool = True,
    heading: Callable[[], float | None] | None = None,
) -> GeometryResult:
    """Solve one base station's pose from two samples a measured distance apart.

    `heading()` reports the drone's yaw in degrees. It is read at each sample
    purely so a failure can say WHICH assumption broke: the maths requires the
    drone to face the same way at both, and "you turned it 40 degrees" is a
    thing the operator can act on where "take them again" is not. It comes
    from the IMU, so it is meaningful as a CHANGE over half a minute even with
    no geometry to give it an absolute reference.
    """
    import numpy as np
    from cflib.localization import LhDeck4SensorPositions

    positions = LhDeck4SensorPositions.positions
    plan = single_station_steps(reference_distance_m)

    def look() -> float | None:
        return heading() if heading is not None else None

    origin = collect(plan[0], 0)
    yaw_at_origin = look()
    forward = collect(plan[1], 0)
    yaw_at_forward = look()
    for sample in (origin, forward):
        sample.augment_with_ippe(positions)

    seen = set(origin.angles_calibrated) & set(forward.angles_calibrated)
    if not seen:
        return GeometryResult(
            converged=False,
            message=(
                "The two samples did not see the same base station, so there is "
                "nothing to solve. Take both without moving or re-aiming it."
            ),
        )
    station = sorted(seen)[0]

    # The drone faced the same way for both samples, so the second one sits at
    # (distance, 0, 0) in the frame being defined. Whichever pairing of the two
    # candidates agrees about where the station is, is the true one.
    offset = np.array([reference_distance_m, 0.0, 0.0])
    best_error = float("inf")
    best_pose = None
    for at_origin in origin.ippe_solutions[station]:
        for at_forward in forward.ippe_solutions[station]:
            disagreement = float(np.linalg.norm(
                (offset + at_forward.translation) - at_origin.translation))
            if disagreement < best_error:
                best_error, best_pose = disagreement, at_origin

    if best_pose is None:                                   # pragma: no cover
        return GeometryResult(converged=False, message="IPPE returned no pose.")
    if best_error > SINGLE_STATION_AGREEMENT_M:
        return GeometryResult(
            converged=False,
            message=_disagreement_reason(
                station, best_error, reference_distance_m,
                yaw_at_origin, yaw_at_forward,
                origin.ippe_solutions[station], forward.ippe_solutions[station], offset),
        )

    result = GeometryResult(
        converged=True,
        stations={station: best_pose},
        mean_error_m=best_error,
        max_error_m=best_error,
        message=(
            f"Solved for base station {station} alone, from two samples "
            f"{reference_distance_m:.2f} m apart that agree to "
            f"{best_error * 100:.1f} cm."
        ),
    )
    if write:
        result.written = _write(cf, {station: best_pose})
    return result


def _turned_by(before: float | None, after: float | None) -> float | None:
    """How far the drone was rotated between the samples, in degrees."""
    if before is None or after is None:
        return None
    return abs((after - before + 180.0) % 360.0 - 180.0)


#: Beyond this the drone was turned enough to explain the disagreement on its
#: own: the second sample is then not "1 m forward along the same heading",
#: which is the one thing the solve assumes.
MAX_TURN_BETWEEN_SAMPLES_DEG = 10.0


def _disagreement_reason(
    station: int,
    error_m: float,
    distance_m: float,
    yaw_before: float | None,
    yaw_after: float | None,
    at_origin: Any,
    at_forward: Any,
    offset: Any,
) -> str:
    """Say which assumption broke, not which three might have."""
    import numpy as np

    turned = _turned_by(yaw_before, yaw_after)
    if turned is not None and turned > MAX_TURN_BETWEEN_SAMPLES_DEG:
        return (
            f"The drone was turned about {turned:.0f} degrees between the two samples. "
            f"The measurement needs it facing the SAME way for both — carry it forward "
            f"without rotating it, and take them again."
        )

    # Both samples put the station somewhere; printing where makes a scale
    # error ("it thinks it is twice as far") tell itself apart from noise.
    far_origin = float(np.linalg.norm(at_origin[0].translation))
    far_forward = float(np.linalg.norm(at_forward[0].translation))
    turn_note = (f" The drone held its heading to {turned:.0f} degrees, so that is "
                 f"not the cause.") if turned is not None else ""
    return (
        f"The two samples disagree about where base station {station} is, by "
        f"{error_m * 100:.0f} cm.{turn_note} From the first it looks "
        f"{far_origin:.2f} m away, from the second {far_forward:.2f} m — those should "
        f"differ by about {distance_m:.2f} m, no more. Most likely the drone did not "
        f"move {distance_m:.2f} m, or the deck was angled away from the station and it "
        f"saw too few of the four sensors. Keep the drone flat, keep its top clear, "
        f"measure the step, and take them again."
    )


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
