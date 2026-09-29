"""Test doubles shaped like the real drone, not like our assumptions about it.

The barometer lookup passed review and shipped with a bug that only the real
drone exposed: cflib's TOC is keyed by *group, then name*, and the code looked
up ``"baro.temp"`` at the top level, where no key can ever match. A flat fake
would have agreed with the bug. These helpers build cflib's own :class:`Toc`
container, so the structure under test is the structure on the drone.
"""

from __future__ import annotations

from types import SimpleNamespace

from cflib.crazyflie.toc import Toc


def make_toc(variables: dict[str, str]) -> Toc:
    """A real cflib Toc from ``{"group.name": "ctype"}``."""
    toc = Toc()
    for ident, (complete_name, ctype) in enumerate(variables.items()):
        group, name = complete_name.split(".")
        toc.add_element(SimpleNamespace(group=group, name=name, ctype=ctype, ident=ident))
    return toc


def fake_scf(
    log_variables: dict[str, str], params: dict[str, str] | None = None
) -> SimpleNamespace:
    """A SyncCrazyflie-shaped object with a real log TOC and a param store."""
    param_values = dict(params or {})

    def get_value(name: str, timeout: float = 0) -> str:
        if name not in param_values:
            raise KeyError(name)
        return param_values[name]

    param_toc = make_toc({name: "uint8_t" for name in param_values})
    cf = SimpleNamespace(
        log=SimpleNamespace(toc=make_toc(log_variables)),
        param=SimpleNamespace(get_value=get_value, toc=param_toc, values=param_values),
    )
    return SimpleNamespace(cf=cf)


# The variables the lab drone actually listed from its TOC on 2026-09-16,
# for the groups this project reads. Used so tests exercise real names.
LAB_DRONE_LOG = {
    "baro.asl": "float",
    "baro.temp": "float",
    "baro.pressure": "float",
    "pm.vbat": "float",
    "stateEstimate.x": "float",
    "stateEstimate.y": "float",
    "stateEstimate.z": "float",
}


# ── the manual flight system ─────────────────────────────────────────────
#
# Shared by tests/test_manual.py and the mission controller's tests: both drive
# the REAL ManualController through these, so a mission test proves the
# controller and the tuned flight system work together.


class FakeCommander:
    """Records every command, so the drone's-eye view can be asserted."""

    def __init__(self):
        self.commands: list[tuple] = []

    def send_setpoint(self, roll, pitch, yaw_rate, thrust):
        self.commands.append(("setpoint", roll, pitch, yaw_rate, thrust))

    def send_hover_setpoint(self, vx, vy, yawrate, zdistance):
        self.commands.append(("hover", vx, vy, yawrate, zdistance))

    def send_zdistance_setpoint(self, roll, pitch, yawrate, zdistance):
        self.commands.append(("zdistance", roll, pitch, yawrate, zdistance))

    def send_position_setpoint(self, x, y, z, yaw):
        self.commands.append(("position", x, y, z, yaw))

    def send_notify_setpoint_stop(self, remain_valid_milliseconds=0):
        self.commands.append(("notify_stop",))

    def send_stop_setpoint(self):
        self.commands.append(("stop",))

    def last(self, kind):
        return next(c for c in reversed(self.commands) if c[0] == kind)

    def kinds(self):
        return [c[0] for c in self.commands]

    #: The setpoints that fly the drone, as opposed to notify/stop bookkeeping.
    FLYING = ("hover", "zdistance", "position", "setpoint")

    def height(self):
        """The commanded height, off whichever setpoint last carried one.

        Which setpoint that is depends on the law and on whether the spot is
        being held, and no test here is about that — they are about the height.
        """
        for c in reversed(self.commands):
            if c[0] in ("hover", "zdistance"):
                return c[4]
            if c[0] == "position":
                return c[3]
        raise AssertionError("nothing carrying a height was ever sent")

    def first_flying(self):
        """Index of the first setpoint that flies the drone."""
        return next(i for i, c in enumerate(self.commands) if c[0] in self.FLYING)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
