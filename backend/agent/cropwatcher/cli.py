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
import threading
import time
from pathlib import Path
from typing import Any

from cropwatcher import paths
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
    geometry.add_argument("--quick", action="store_true",
                          help="one sample, one position, no measuring — restores "
                               "position hold now; forward/back may come out mirrored")
    geometry.add_argument("--countdown", type=float, metavar="SECONDS",
                          help="take each sample after a countdown instead of on Enter, "
                               "for when both hands are holding the drone")
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

    sub.add_parser("selftest", help="load every library the agent only loads on demand")
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
        # What is actually RECEIVED decides the method — not what the drone has
        # stored, which is last session's memory and says nothing about now.
        received = assess_positioning(link.snapshot()).received
        alone = len(received) < 2

        print("\n  MEASURING WHERE THE BASE STATIONS ARE")
        print("  The drone is carried by hand throughout. No motor will spin.")
        print("  Keep yourself out of the line between the stations and the drone.")
        seen = ", ".join(str(b) for b in sorted(received))
        if args.quick:
            print("\n  QUICK: one sample at one position, no measuring.")
            print("  This restores position hold now. It can pick the mirror of the")
            print("  true answer, so if forward turns out to be backward, run this")
            print("  again without --quick.")
        elif alone and seen:
            print(f"\n  Only base station {seen} is being received, so this measures")
            print("  that one alone, from two samples a measured distance apart.")
            print("  Both samples must see it, and the drone must face the same")
            print("  way for both — the second sample is what rules out a")
            print("  mirror-image answer where forward comes out backward.")
        elif alone:
            print("\n  No base station is being received YET. Put the drone flat with")
            print("  its top clear and give it a few seconds; the sample will wait.")
        print()

        reader = geometry_estimation.SweepAngles(
            scf.cf, min_stations=1 if alone else 2)

        def ready(prompt: str) -> None:
            """Wait for the operator — by the keyboard, or by the clock.

            Someone alone in a cage is holding the drone with both hands at
            the position being measured. Reaching back to a keyboard moves the
            very thing the sample is of.
            """
            if args.countdown is None:
                input(f"  {prompt}: ")
                return
            print(f"  {prompt} — sampling in:", end="", flush=True)
            for remaining in range(int(args.countdown), 0, -1):
                print(f" {remaining}", end="", flush=True)
                time.sleep(1.0)
            print("  now — hold still")

        def collect(step: geometry_estimation.GeometryStep, index: int) -> object:
            total = step.count
            label = f" ({index + 1} of {total})" if total > 1 else ""
            while True:
                print(f"\n  {step.instruction}{label}")
                ready("Press Enter when it is there and steady"
                      if args.countdown is None else "Get it into position")
                try:
                    sample = reader.record()
                except (TimeoutError, ValueError) as e:
                    print(f"    {e}")
                    continue
                print("    recorded")
                return sample

        def heading() -> float | None:
            """The drone's yaw, so a failure can say if it was turned."""
            value = link.snapshot().get("stabilizer.yaw")
            return None if value is None else float(value)

        try:
            if args.quick:
                result = geometry_estimation.estimate_quick(
                    scf.cf, collect, write=not args.dry_run)
            elif alone:
                result = geometry_estimation.estimate_single(
                    scf.cf, collect,
                    reference_distance_m=args.distance,
                    write=not args.dry_run,
                    heading=heading,
                )
            else:
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
        if not alone:
            print(f"  error   mean {result.mean_error_m * 100:.1f} cm, "
                  f"worst {result.max_error_m * 100:.1f} cm")
        if result.written:
            print("  stored on the drone — it survives a power cycle")
        elif args.dry_run:
            print("  not written (--dry-run)")
        else:
            print("  WARNING: the drone did not confirm the write")
        if alone:
            print("\n  One station carries no redundancy: lose sight of it and x and y")
            print("  become the accelerometer integrating. Set CROPWATCHER_MIN_STATIONS=1")
            print("  to let the checks accept it.")
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


#: Everything the agent imports only when a feature is first used — inside a
#: function, so starting the agent proves nothing about them. A frozen Intel
#: agent (2026-09-25) started and served, while `supabase` could not be
#: imported at all: cryptography, which it needs, had been compiled against
#: Homebrew's OpenSSL, and the frozen bundle kept Python's older libssl under
#: the same file name. Sign-in was the first thing to import it.
SELFTEST_MODULES = (
    "supabase",                                         # sign-in, sync
    "cryptography.hazmat.bindings._rust",               # its native half, via PyJWT
    "numpy",                                            # geometry
    "cflib.localization.lighthouse_geo_estimation_manager",   # geometry (scipy)
    "cflib.localization",                               # geometry, config writer
    "cflib.crazyflie.mem.lighthouse_memory",            # geometry
    "cflib.bootloader",                                 # firmware flashing
    "cflib.cpx",                                        # the AI deck's camera
    "libusb_package",                                   # the radio, and radio.py
    "usb.backend.libusb1",
    "uvicorn",                                          # serve
)


def cmd_selftest(_args: argparse.Namespace) -> int:
    """Import every lazily loaded library; report each one that will not load.

    packaging/verify_sidecar.py runs this against the frozen binary on every
    build, so a library that is broken inside the bundle fails the build on
    that machine instead of failing a feature on an operator's desk.
    """
    import importlib

    failed = []
    for name in SELFTEST_MODULES:
        try:
            importlib.import_module(name)
        except Exception as e:                 # ImportError, OSError from dlopen, …
            failed.append(name)
            print(f"  FAILED  {name}: {type(e).__name__}: {e}")
    # PyJWT treats a missing cryptography as "no asymmetric algorithms" rather
    # than an error, so an excluded or unimportable one would pass the loop.
    try:
        from jwt.algorithms import has_crypto
    except Exception as e:
        failed.append("jwt.algorithms")
        print(f"  FAILED  jwt.algorithms: {type(e).__name__}: {e}")
    else:
        if not has_crypto:
            failed.append("jwt crypto")
            print("  FAILED  PyJWT loaded without cryptography")
    if failed:
        print(f"\n  {len(failed)} of {len(SELFTEST_MODULES) + 1} did not load")
        return 1
    print(f"  imports ok ({len(SELFTEST_MODULES) + 1} checked)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from cropwatcher.api.rest import serve as run_server

    print(f"  agent API on http://{args.host}:{args.port}")
    run_server(host=args.host, port=args.port, exit_with_parent=args.exit_with_parent)
    return 0


def _start_logging(*, verbose: bool) -> None:
    """Log to the terminal AND to a file that outlives the process.

    The desktop app discards the sidecar's stdout, so a crash inside the agent
    left the operator with "Could not reach the flight agent" and no way to
    find out why. The file is capped and rotated: a flight log is worth
    keeping, a gigabyte of it is not.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(
            paths.log_file(), maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    except Exception:                       # a read-only home must not stop a flight
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    # An exception that kills a thread otherwise vanishes with it.
    def _thread_died(args: Any) -> None:
        logging.getLogger("cropwatcher").critical(
            "unhandled exception in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    threading.excepthook = _thread_died
    sys.excepthook = lambda *e: logging.getLogger("cropwatcher").critical(
        "unhandled exception", exc_info=e)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _start_logging(verbose=args.verbose)

    handlers = {
        "check": cmd_check,
        "stations": cmd_stations,
        "geometry": cmd_geometry,
        "proptest": cmd_proptest,
        "hover": cmd_hover,
        "mission": cmd_mission,
        "lawnmower": cmd_lawnmower,
        "serve": cmd_serve,
        "selftest": cmd_selftest,
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
