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
