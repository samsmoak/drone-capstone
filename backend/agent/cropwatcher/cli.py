"""Command line entry point.

This is the whole point of ``flight.core``: every parameter is an argument.
Nothing here prompts, and nothing has to be edited between flights.

    cropwatcher check                       # preflight only, no motors
    cropwatcher hover --height 0.5 --secs 30
    cropwatcher goto --x 0.3 --y -0.2 --z 0.5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from cropwatcher.flight import core, missions
from cropwatcher.flight.core import Waypoint
from cropwatcher.flight.missions import (
    Mission,
    MissionValidationError,
    lawnmower_mission,
)
from cropwatcher.flight.preflight import PreflightError
from cropwatcher.safety.geofence import Geofence
from cropwatcher.safety.occupancy import OccupancyGrid
from cropwatcher.telemetry.correction import ThermalEngine
from cropwatcher.telemetry.reader import TelemetryReader, detect_baro_vars, read_initial
from cropwatcher.telemetry.row import TempUnit, parse_ambient
from cropwatcher.telemetry.sinks import CsvSink

log = logging.getLogger("cropwatcher")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--uri", default=core.DEFAULT_URI, help="Crazyflie radio URI")
    p.add_argument(
        "--force",
        action="store_true",
        help="skip advisory gates (endurance, estimate stability). Never skips "
             "the physical ones — no positioning deck still means no flight.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cropwatcher", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run preflight only; never spins a motor")
    _add_common(check)

    hover = sub.add_parser("hover", help="take off, hold altitude, land")
    hover.add_argument("--height", type=float, default=0.5, help="metres above ground")
    hover.add_argument("--secs", type=float, default=5.0, help="hold duration")
    hover.add_argument(
        "--ambient",
        default="22C",
        help="room temperature, e.g. 74F or 22C. The unit you use here is the "
             "unit every temperature column is stored in.",
    )
    hover.add_argument("--no-log", action="store_true", help="skip CSV logging")
    _add_common(hover)

    goto = sub.add_parser("goto", help="take off, fly to one point, return, land")
    goto.add_argument("--x", type=float, required=True, help="metres")
    goto.add_argument("--y", type=float, required=True, help="metres")
    goto.add_argument("--z", type=float, required=True, help="metres above ground")
    goto.add_argument("--secs", type=float, default=3.0, help="travel duration")
    _add_common(goto)

    lawn = sub.add_parser("lawnmower", help="serpentine scan of a rectangle")
    lawn.add_argument("--width", type=float, default=2.0, help="metres")
    lawn.add_argument("--height", type=float, default=2.0, help="metres")
    lawn.add_argument("--step", type=float, default=0.5, help="lane spacing, metres")
    lawn.add_argument("--altitude", type=float, default=0.5, help="metres above ground")
    lawn.add_argument("--layers", type=int, default=1)
    lawn.add_argument("--hold", type=float, default=0.0, help="dwell per waypoint")
    _add_mission_common(lawn)
    _add_common(lawn)

    run = sub.add_parser("mission", help="fly a saved mission file")
    run.add_argument("--file", required=True, help="path to a mission JSON file")
    _add_mission_common(run)
    _add_common(run)

    return parser


def _add_mission_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the plan; never connects, never arms",
    )
    p.add_argument("--fence", type=float, default=2.0,
                   help="half-extent of the square geofence, metres")
    p.add_argument("--map", help="occupancy map YAML for path checking")
    p.add_argument("--ambient", default="22C", help="room temperature, e.g. 74F")
    p.add_argument("--save", help="write the generated plan to this path")


def cmd_check(args: argparse.Namespace) -> int:
    with core.connect(args.uri) as scf:
        from cropwatcher.flight import preflight

        report = preflight.run(scf, hold_seconds=0.0, force=args.force)

    print(f"  battery       {report.vbat:.2f} V")
    print(f"  firmware      canfly={int(report.can_fly)}")
    print(f"  base stations {report.base_stations}")
    print(f"  ground z      {report.ground_z_m:+.3f} m "
          f"(settled to {report.estimate_spread_m * 100:.1f} cm)")
    print(f"  endurance     ~{report.endurance_s:.0f}s of hover")
    print("\n  READY")
    return 0


def cmd_hover(args: argparse.Namespace) -> int:
    ambient_c, unit = parse_ambient(args.ambient)

    with core.session(args.uri, hold_seconds=args.secs, force=args.force) as flight:
        print(f"  battery {flight.report.vbat:.2f} V, "
              f"ground z {flight.ground_z:+.3f} m")

        reader, csv_path = (None, None)
        if not args.no_log:
            reader, csv_path = _start_logging(flight, ambient_c, unit)

        try:
            print(f"\n  taking off to {args.height:.2f} m above ground")
            flight.takeoff(args.height)

            elapsed = 0.0
            while elapsed < args.secs:
                _, _, z = flight.position()
                vbat = flight.battery()
                print(f"   {z:5.2f} m AGL   err={z - args.height:+.3f} m   {vbat:.2f} V")
                if vbat < core.preflight.CRITICAL_VBAT:
                    print("   VOLTAGE CRITICAL — landing early")
                    break
                flight.hold(0.25)
                elapsed += 0.25

            print("\n  landing")
            flight.land()
        finally:
            # Stop logging after landing, not before: the correction engine
            # needs the idle samples either side of the flight.
            if reader is not None:
                reader.stop()
                print(f"  telemetry written to {csv_path}")

    print("  done")
    return 0


def _start_logging(
    flight: core.Flight, ambient_c: float, unit: TempUnit
) -> tuple[TelemetryReader, Path]:
    """Seed the correction engine from a real reading, then start streaming."""
    scf = flight.scf
    temp_var, press_var = detect_baro_vars(scf)
    raw_c, _pressure = read_initial(scf, temp_var, press_var)
    print(f"  startup temp {raw_c:.2f} C, ambient given as {ambient_c:.2f} C "
          f"(storing in {unit})")

    sink = CsvSink()
    reader = TelemetryReader(
        scf,
        sink,
        ThermalEngine(raw_c, ambient_c),
        unit=unit,
        ground_z=flight.ground_z,
    )
    reader.start()
    return reader, sink.path


def cmd_goto(args: argparse.Namespace) -> int:
    target = Waypoint(args.x, args.y, args.z)
    with core.session(args.uri, hold_seconds=args.secs * 2, force=args.force) as flight:
        print(f"  taking off to {args.z:.2f} m")
        flight.takeoff(args.z)

        print(f"  flying to ({target.x:+.2f}, {target.y:+.2f}, {target.z:.2f})")
        flight.goto(target, duration_s=args.secs)
        x, y, z = flight.position()
        print(f"  arrived at ({x:+.3f}, {y:+.3f}, {z:.3f})")

        print("  returning to start")
        flight.goto(Waypoint(0.0, 0.0, args.z), duration_s=args.secs)
        flight.land()
    print("  done")
    return 0


def cmd_lawnmower(args: argparse.Namespace) -> int:
    mission = lawnmower_mission(
        width_m=args.width,
        height_m=args.height,
        step_m=args.step,
        altitude_m=args.altitude,
        layers=args.layers,
        hold_s=args.hold,
    )
    return _plan_and_fly(mission, args)


def cmd_mission(args: argparse.Namespace) -> int:
    return _plan_and_fly(Mission.from_file(args.file), args)


def _plan_and_fly(mission: Mission, args: argparse.Namespace) -> int:
    """Validate, print, then fly — unless this is a dry run.

    Validation happens with no drone connected, so an operator can check a
    route from a desk before carrying anything to the greenhouse.
    """
    geofence = Geofence.square(args.fence)
    occupancy = OccupancyGrid.from_yaml(args.map) if args.map else None

    print(mission.describe())
    print()

    try:
        mission.validate(geofence=geofence, occupancy=occupancy)
    except MissionValidationError as e:
        print(f"  PLAN REJECTED — {e}\n", file=sys.stderr)
        return 3
    print("  plan validated"
          f" against a {args.fence * 2:.1f} m square fence"
          + (" and the occupancy map" if occupancy else " (no map supplied)"))

    if args.save:
        mission.save(args.save)
        print(f"  saved to {args.save}")

    if args.dry_run:
        print("\n  DRY RUN — nothing was armed\n")
        return 0

    ambient_c, unit = parse_ambient(args.ambient)
    estimated = mission.estimated_duration_s()

    with core.session(args.uri, hold_seconds=estimated, force=args.force) as flight:
        reader, csv_path = _start_logging(flight, ambient_c, unit)
        try:
            for event in missions.execute(mission, flight):
                print(f"   [{event.kind}] {event.detail}")
        finally:
            reader.stop()
            print(f"\n  telemetry written to {csv_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    handlers = {
        "check": cmd_check,
        "hover": cmd_hover,
        "goto": cmd_goto,
        "lawnmower": cmd_lawnmower,
        "mission": cmd_mission,
    }
    try:
        return handlers[args.command](args)
    except PreflightError as e:
        # A refused preflight is an expected outcome, not a crash. Say what the
        # drone said and what to do about it.
        print(f"\n  REFUSED — {e.detail}\n", file=sys.stderr)
        return 2
    except core.FlightError as e:
        print(f"\n  {e}\n", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n  aborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
