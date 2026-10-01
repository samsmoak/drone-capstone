"""The lines between the parts, held by tests rather than by good intentions.

- mission/plan never imports the flight code: a plan is drawn, checked and
  saved with no drone.
- The manual flight system satisfies MissionFlight, the only surface the
  mission controller may use.
- The mission controller is built, so the session arms a mission and hands the
  real controller the armed manual flight system (experiment/samuel: this was
  "the skeleton refuses to start" until the body was built).
"""

from __future__ import annotations

import subprocess
import sys

from cropwatcher.flight.manual import ControlState, ManualController
from cropwatcher.mission.controller import MissionController, MissionFlight, MissionState
from cropwatcher.session import State
from tests.fakes import FakeClock, FakeCommander
from tests.mission.plans import mission
from tests.mission.test_session_missions import make_rig
from tests.test_session import FakeManual, wait_for


def _imported_by(module: str) -> set[str]:
    code = (f"import sys, {module}; "
            f"print('\\n'.join(m for m in sys.modules if m.startswith('cropwatcher')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True)
    return set(out.stdout.split())


def test_the_plan_package_never_imports_the_flight_code():
    loaded = _imported_by("cropwatcher.mission.plan.validate, cropwatcher.mission.plan.store")
    assert not {m for m in loaded if m.startswith("cropwatcher.flight")}
    assert "cropwatcher.session" not in loaded


def test_the_manual_flight_system_is_a_mission_flight():
    flight: MissionFlight = ManualController(
        FakeCommander(), ground_z=0.0, land=lambda z, d: None, clock=FakeClock())
    for name in ("state", "assisted", "target", "target_height", "drift_m",
                 "goal_active", "operator_override", "hold_at", "fly_to", "land"):
        assert hasattr(flight, name), name


class FlyableFakeManual(FakeManual):
    """The session tests' fake manual system, with the MissionFlight surface
    the real controller reads and the one command start() gives."""

    state = ControlState.ARMED
    assisted = True
    goal_active = True
    operator_override = False
    drift_m = 0.0
    target = None
    target_height = 0.0

    def hold_at(self, height_m: float) -> None:
        self.events.append(f"hold_at {height_m:.2f}")

    def fly_to(self, x: float, y: float, height_m: float,
               speed_m_s: float | None = None) -> None:
        self.events.append("fly_to")


def test_the_session_arms_a_mission_and_the_real_controller_takes_off(tmp_path, monkeypatch):
    assert MissionController.BUILT is True
    rig = make_rig(tmp_path, monkeypatch, controller=MissionController)
    rig.link.manual_controller = FlyableFakeManual()
    rig.session.run_mission("m1")
    manual = rig.link.manual_controller
    assert wait_for(lambda: any(e.startswith("hold_at") for e in manual.events))
    assert manual.events[:2] == ["arm", "start"]
    assert manual.events[2] == f"hold_at {mission().cruise_height_m:.2f}"
    flying = rig.session.mission
    assert isinstance(flying, MissionController)
    assert flying.state is MissionState.TAKING_OFF
    assert wait_for(lambda: (rig.session.snapshot().mission or {}).get("last_event", {})
                    .get("kind") == "started")
    flying.abort("the test is over")
    assert flying.state is MissionState.ABORTED
    # Bring the flight down and let the session's own processing of it finish,
    # so nothing is still logging from a worker thread after the test ends.
    manual.state = ControlState.LANDED
    assert wait_for(lambda: rig.session.snapshot().state is State.READY)
    assert rig.session.processing.wait_idle()
