"""Command line entry point.

For the lab and for diagnostics. The desktop app is what an operator uses; this
is what you reach for when a drone will not connect and there is no window to
click in.

    cropwatcher check                       # every gate, no motors
    cropwatcher proptest                    # the firmware's motor test
    cropwatcher hover --height 0.3 --secs 10 --ambient 74F
    cropwatcher mission --file plan.json
    cropwatcher serve                       # the local API for the desktop app

Every flight here goes through the same :class:`DroneLink` the app uses, so the
checks and the in-flight guards are identical. Nothing prompts, and nothing has
to be edited between flights.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from cropwatcher.flight import core
from cropwatcher.flight import geometry as geometry_estimation
from cropwatcher.flight.checks import CheckResult, ChecksFailed, CheckStatus, ReadyReport, collect
from cropwatcher.flight.control import FlightAborted
from cropwatcher.flight.link import DroneLink, LinkError
from cropwatcher.flight.missions import Mission, MissionValidationError, execute, lawnmower_mission
from cropwatcher.flight.programs import HoverTest, run_hover_test
from cropwatcher.paths import flights_dir
from cropwatcher.safety.flight_guard import assess_positioning
from cropwatcher.safety.geofence import Geofence
from cropwatcher.telemetry.reader import FlightRecorder
from cropwatcher.telemetry.row import parse_ambient
from cropwatcher.telemetry.sinks import CsvSink

log = logging.getLogger("cropwatcher")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--uri", default=core.DEFAULT_URI, help="Crazyflie radio URI")


def _add_flight_common(p: argparse.ArgumentParser) -> None:
    _add_common(p)
    p.add_argument(
        "--ambient", default="22C",
        help="room temperature, e.g. 74F or 22C. The unit you use here is the "
             "unit every temperature in this flight is stored in.",
    )
    p.add_argument("--fence", type=float, default=2.0,
                   help="half-extent of the square geofence, metres")
    p.add_argument("--no-log", action="store_true", help="fly without recording a CSV")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cropwatcher", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="run every gate; never spins a motor")
    _add_common(check)

    stations = sub.add_parser(
        "stations", help="watch which base stations the drone can see, live")
    _add_common(stations)
    stations.add_argument("--seconds", type=float, default=0.0,
                          help="stop after this long (default: until Ctrl-C)")

    geometry = sub.add_parser(
        "geometry", help="measure where the base stations are; no motors spin")
    _add_common(geometry)
    geometry.add_argument("--distance", type=float, default=1.0,
                          help="how far the x-axis sample is from the origin, in metres")
    geometry.add_argument("--dry-run", action="store_true",
                          help="solve but do not write the result to the drone")

    proptest = sub.add_parser("proptest", help="the firmware's propeller test — motors spin")
    _add_common(proptest)

    hover = sub.add_parser("hover", help="take off, hold a steady height, land")
    hover.add_argument("--height", type=float, default=0.3, help="metres above the floor")
    hover.add_argument("--secs", type=float, default=10.0, help="hold duration")
    _add_flight_common(hover)

    mission = sub.add_parser("mission", help="fly a saved mission file")
    mission.add_argument("--file", required=True, help="path to a mission JSON file")
    _add_flight_common(mission)

    lawn = sub.add_parser("lawnmower", help="write a serpentine scan to a mission file")
    lawn.add_argument("--width", type=float, required=True, help="metres")
    lawn.add_argument("--height-m", type=float, required=True, help="metres")
    lawn.add_argument("--step", type=float, default=0.5, help="lane spacing, metres")
    lawn.add_argument("--altitude", type=float, default=0.5, help="metres above the floor")
    lawn.add_argument("--out", required=True, help="where to write the plan")

    serve = sub.add_parser("serve", help="run the local API for the desktop app")
    serve.add_argument("--host", default="127.0.0.1",
                       help="binding beyond localhost exposes drone control")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--exit-with-parent", action="store_true",
        help="land, cut motors and exit when stdin closes. The desktop app passes "
             "this so quitting it cannot strand an agent holding the radio.",
    )
    return parser


# ── shared ───────────────────────────────────────────────────────────────


def _print_step(step: CheckResult) -> None:
    if step.status is CheckStatus.RUNNING:
        return
    mark = "ok  " if step.status is CheckStatus.PASSED else "FAIL"
    print(f"  {mark} {step.label:22} {step.detail}")


def _run_checks(link: DroneLink) -> ReadyReport:
    print("  checks:")
    return collect(link.checks(), _print_step)


def _record(link: DroneLink, report: ReadyReport, args, flight_id: str) -> FlightRecorder | None:
    if args.no_log:
        return None
    ambient_c, unit = parse_ambient(args.ambient)
    sink = CsvSink(root=flights_dir(), prefix=f"flight_{flight_id}")
    assert link.stream is not None
    recorder = FlightRecorder(
        link.stream, sink, ambient_c=ambient_c, unit=unit,
        ground_z=report.ground_z_m, flight_id=flight_id,
    )
    recorder.start()
    print(f"  recording to {sink.path}")
    return recorder


def _confirm_area() -> bool:
    """The same confirmation the desktop app requires before motors turn."""
    answer = input("  Is the drone on the floor with the area clear? [y/N] ").strip().lower()
    return answer in ("y", "yes")


# ── commands ─────────────────────────────────────────────────────────────


def cmd_check(args: argparse.Namespace) -> int:
    with DroneLink(args.uri) as link:
        report = _run_checks(link)
        print(f"\n  drone      {report.hardware_id}")
        print(f"  battery    {report.vbat:.2f} V, ~{report.endurance_s:.0f}s of hover")
        print(f"  stations   {', '.join(str(s) for s in report.positioning.usable)}")
        print(f"  ground z   {report.ground_z_m:+.3f} m "
              f"(settled to {report.estimate_spread_m * 100:.1f} cm)")
        print("\n  READY")
    return 0


def cmd_stations(args: argparse.Namespace) -> int:
    """Watch the Lighthouse, live, while someone moves or powers a station.

    Written in the lab (2026-09-21) with one station reaching the drone and the
    other set up but unseen. Standing at the drone, reading what the DRONE
    reports, is the only way to tell "the LED is on" from "the drone can see
    it" — and two received stations is the difference between a drone that
    holds position and one that hops sideways.

    Reads only. No motors, no arming.
    """
    def which(mask: float | None) -> str:
        if mask is None:
            return "—"
        bits = [str(i) for i in range(16) if int(mask) >> i & 1]
        return ", ".join(bits) if bits else "none"

    with DroneLink(args.uri) as link:
        print("\n  Watching the Lighthouse. Ctrl-C to stop.\n")
        print("   received   calibrated   geometry   estimate (x, y, z)        verdict")
        deadline = time.monotonic() + args.seconds if args.seconds else None
        try:
            while deadline is None or time.monotonic() < deadline:
                snap = link.snapshot()
                status = assess_positioning(snap)
                x = snap.get("stateEstimate.x")
                y = snap.get("stateEstimate.y")
                z = snap.get("stateEstimate.z")
                where = (f"{x:+.2f} {y:+.2f} {z:+.2f}"
                         if None not in (x, y, z) else "      —      ")
                verdict = ("READY — hold position"
                           if status.ready else
                           " ".join(status.problems())[:46])
                print(f"   {which(snap.get('lighthouse.bsReceive')):<10} "
                      f"{which(snap.get('lighthouse.bsCalVal')):<12} "
                      f"{which(snap.get('lighthouse.bsGeoVal')):<10} "
                      f"{where:<24} {verdict}")
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n  stopped\n")
    return 0


def cmd_geometry(args: argparse.Namespace) -> int:
    """Measure where the base stations are, with the drone carried by hand.

    Stale geometry is silent: the stations disagree and the estimate jumps
    rather than failing, which is what the lab drone was doing on 2026-09-21 —
    21 cm in a tenth of a second while sitting still. Nothing downstream can
    recover from a position that is lying, so this is the first thing to fix
    when a drone will not hold still.
    """
    with DroneLink(args.uri) as link:
        scf = link.scf
        reader = geometry_estimation.SweepAngles(scf.cf)

        print("\n  MEASURING WHERE THE BASE STATIONS ARE")
        print("  The drone is carried by hand throughout. No motor will spin.")
        print("  Keep yourself out of the line between the stations and the drone.\n")

        def collect(step: geometry_estimation.GeometryStep, index: int) -> object:
            total = step.count
            label = f" ({index + 1} of {total})" if total > 1 else ""
            while True:
                print(f"\n  {step.instruction}{label}")
                input("  Press Enter when it is there and steady: ")
                try:
                    sample = reader.record()
                except (TimeoutError, ValueError) as e:
                    print(f"    {e}")
                    continue
                print("    recorded")
                return sample

        try:
            result = geometry_estimation.estimate(
                scf.cf, collect,
                reference_distance_m=args.distance,
                write=not args.dry_run,
            )
        except KeyboardInterrupt:
            print("\n  stopped — nothing was written to the drone\n")
            return 1

        print()
        if not result.converged:
            print(f"  {result.message}\n")
            return 1
        print(f"  {result.message}")
        print(f"  error   mean {result.mean_error_m * 100:.1f} cm, "
              f"worst {result.max_error_m * 100:.1f} cm")
        if result.written:
            print("  stored on the drone — it survives a power cycle")
        elif args.dry_run:
            print("  not written (--dry-run)")
        else:
            print("  WARNING: the drone did not confirm the write")
        print("\n  Now run:  cropwatcher check     (it should settle under 2 cm)\n")
    return 0


def cmd_proptest(args: argparse.Namespace) -> int:
    with DroneLink(args.uri) as link:
        _run_checks(link)
        if not _confirm_area():
            print("  cancelled")
            return 1
        result = link.prop_test()
        for motor in (1, 2, 3, 4):
            print(f"  motor {motor}   {'ok' if motor in result.passed else 'FAILED'}")
        return 0 if result.ok else 1


def cmd_hover(args: argparse.Namespace) -> int:
    program = HoverTest(height_m=args.height, hold_s=args.secs)
    with DroneLink(args.uri) as link:
        report = _run_checks(link)
        if program.duration_s() > report.budget_s():
            print(f"\n  this battery has about {report.budget_s():.0f}s of flying left; "
                  f"the program needs {program.duration_s():.0f}s")
            return 1
        if not _confirm_area():
            print("  cancelled")
            return 1

        recorder = _record(link, report, args, flight_id="cli")
        flight = link.guarded_flight(
            report, target_height_m=program.height_m, fence_half_extent_m=args.fence,
            on_phase=lambda event: print(f"  {event.phase}: {event.detail}"),
        )
        try:
            result = run_hover_test(flight, program)
        finally:
            if recorder is not None:
                recorder.stop()
        print(f"\n  {result.message}")
        return 0 if result.outcome.value == "completed" else 1


def cmd_mission(args: argparse.Namespace) -> int:
    try:
        mission = Mission.from_file(args.file)
    except (OSError, ValueError) as e:
        print(f"  could not read the mission: {e}")
        return 2
    try:
        mission.validate(geofence=Geofence.square(args.fence))
    except MissionValidationError as e:
        print(f"  the plan is not safe to fly: {e}")
        return 2

    with DroneLink(args.uri) as link:
        report = _run_checks(link)
        if mission.estimated_duration_s() > report.budget_s():
            print(f"\n  this battery has about {report.budget_s():.0f}s of flying left; "
                  f"the mission needs {mission.estimated_duration_s():.0f}s")
            return 1
        if not _confirm_area():
            print("  cancelled")
            return 1

        recorder = _record(link, report, args, flight_id="cli")
        flight = link.guarded_flight(
            report, target_height_m=mission.altitude_m, hold_position=False,
            fence_half_extent_m=args.fence,
        )
        try:
            for event in execute(mission, flight):
                print(f"  {event.kind}: {event.detail}")
        except FlightAborted as e:
            print(f"\n  {e.verdict.message}")
            return 1
        finally:
            if recorder is not None:
                recorder.stop()
    return 0


def cmd_lawnmower(args: argparse.Namespace) -> int:
    mission = lawnmower_mission(
        width_m=args.width, height_m=args.height_m, step_m=args.step, altitude_m=args.altitude,
    )
    Path(args.out).write_text(json.dumps(mission.to_dict(), indent=2), encoding="utf-8")
    print(f"  {len(mission.waypoints)} waypoints, about "
          f"{mission.estimated_duration_s():.0f}s → {args.out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from cropwatcher.api.rest import serve as run_server

    print(f"  agent API on http://{args.host}:{args.port}")
    run_server(host=args.host, port=args.port, exit_with_parent=args.exit_with_parent)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    handlers = {
        "check": cmd_check,
        "stations": cmd_stations,
        "geometry": cmd_geometry,
        "proptest": cmd_proptest,
        "hover": cmd_hover,
        "mission": cmd_mission,
        "lawnmower": cmd_lawnmower,
        "serve": cmd_serve,
    }
    try:
        return handlers[args.command](args)
    except LinkError as e:
        print(f"\n  {e}\n")
        return 1
    except ChecksFailed as e:
        print(f"\n  {e.result.detail}\n")
        return 1
    except FlightAborted as e:
        print(f"\n  {e.verdict.message}\n")
        return 1
    except KeyboardInterrupt:
        print("\n  interrupted — the drone lands on the way out")
        return 130


if __name__ == "__main__":
    sys.exit(main())
