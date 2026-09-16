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

from cropwatcher.flight import core
from cropwatcher.flight.core import Waypoint
from cropwatcher.flight.preflight import PreflightError

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
    _add_common(hover)

    goto = sub.add_parser("goto", help="take off, fly to one point, return, land")
    goto.add_argument("--x", type=float, required=True, help="metres")
    goto.add_argument("--y", type=float, required=True, help="metres")
    goto.add_argument("--z", type=float, required=True, help="metres above ground")
    goto.add_argument("--secs", type=float, default=3.0, help="travel duration")
    _add_common(goto)

    return parser


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
    with core.session(args.uri, hold_seconds=args.secs, force=args.force) as flight:
        print(f"  battery {flight.report.vbat:.2f} V, "
              f"ground z {flight.ground_z:+.3f} m\n")
        print(f"  taking off to {args.height:.2f} m above ground")
        flight.takeoff(args.height)

        deadline = args.secs
        elapsed = 0.0
        while elapsed < deadline:
            x, y, z = flight.position()
            vbat = flight.battery()
            print(f"   {z:5.2f} m AGL   err={z - args.height:+.3f} m   {vbat:.2f} V")
            if vbat < core.preflight.CRITICAL_VBAT:
                print("   VOLTAGE CRITICAL — landing early")
                break
            flight.hold(0.25)
            elapsed += 0.25

        print("\n  landing")
        flight.land()
    print("  done")
    return 0


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    handlers = {"check": cmd_check, "hover": cmd_hover, "goto": cmd_goto}
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
