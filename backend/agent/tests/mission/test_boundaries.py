"""The lines between the parts, held by tests rather than by good intentions.

- mission/plan never imports the flight code: a plan is drawn, checked and
  saved with no drone.
- The manual flight system satisfies MissionFlight, the only surface the
  mission controller may use.
- Until Hannah's body lands, the mission controller refuses to start.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from cropwatcher.flight.manual import ManualController
from cropwatcher.mission.controller import MissionController, MissionError, MissionFlight
from tests.fakes import FakeClock, FakeCommander
from tests.mission.plans import mission


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


def test_the_skeleton_refuses_to_start_and_says_where_the_work_is():
    flight = ManualController(FakeCommander(), ground_z=0.0, land=lambda z, d: None,
                              clock=FakeClock())
    controller = MissionController(mission(), flight, on_event=lambda e: None)
    assert MissionController.BUILT is False
    with pytest.raises(MissionError, match="handoffs/mission-controller.txt"):
        controller.start()
    assert controller.current_point_id is None
