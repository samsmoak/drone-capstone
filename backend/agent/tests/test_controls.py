"""The arrow keys' frame and the operator's spot: saved, and handed to a flight."""

from __future__ import annotations

import json
from types import MappingProxyType, SimpleNamespace

import pytest

from cropwatcher.flight.controls_store import Controls, ControlsStore
from cropwatcher.flight.keyframe import ActiveFrame, FrameStatus, KeyFrame
from cropwatcher.session import Mode, SessionError
from cropwatcher.telemetry.stream import Snapshot
from tests.mission.test_session_missions import POSITIONED
from tests.test_session import rig, start_and_confirm  # noqa: F401 — the fixture


class TestStore:
    def test_a_fresh_laptop_gets_the_defaults(self, tmp_path):
        assert ControlsStore(tmp_path / "controls.json").load() == Controls()

    def test_what_is_saved_comes_back(self, tmp_path):
        store = ControlsStore(tmp_path / "controls.json")
        saved = Controls().with_frame(KeyFrame.ROOM).with_operator((1.23456, -0.5))
        store.save(saved)
        loaded = store.load()
        assert loaded.key_frame is KeyFrame.ROOM
        assert loaded.operator == (1.2346, -0.5)
        assert loaded.operator_marked_at == saved.operator_marked_at
        assert not (tmp_path / "controls.json.tmp").exists()

    @pytest.mark.parametrize("content", [
        "not json", "[]", '{"key_frame": "nose"}',
        '{"operator": [1, 2, 3]}', '{"operator": [999, 0]}', '{"operator": ["a", "b"]}',
    ])
    def test_a_bad_file_is_the_defaults_never_an_error(self, tmp_path, content):
        path = tmp_path / "controls.json"
        path.write_text(content)
        loaded = ControlsStore(path).load()
        assert loaded.key_frame is KeyFrame.OPERATOR
        assert loaded.operator is None

    def test_a_file_from_the_nose_and_speed_builds_still_loads(self, tmp_path):
        """Those builds (2026-09-30) saved a nose and a speed; a saved nose
        rotated the arrows before takeoff, flight after flight. Both ignored."""
        path = tmp_path / "controls.json"
        path.write_text('{"key_frame": "room", "nose": "towards", "speed": "slow"}')
        loaded = ControlsStore(path).load()
        assert loaded.key_frame is KeyFrame.ROOM
        assert set(loaded.to_dict()) == {"key_frame", "operator", "operator_marked_at"}

    def test_clearing_the_spot_clears_its_date(self):
        c = Controls().with_operator((1.0, 1.0)).with_operator(None)
        assert c.operator is None and c.operator_marked_at is None


def position(rig, x, y):  # noqa: F811 — `rig` is the fixture's name
    values = {**POSITIONED, "stateEstimate.x": x, "stateEstimate.y": y, "stateEstimate.z": 0.01}
    rig.link.stream.snapshot = lambda: Snapshot(MappingProxyType(values), 1.0)


class TestSession:
    def test_the_snapshot_starts_with_what_was_saved(self, rig):  # noqa: F811
        controls = rig.session.snapshot().to_dict()["controls"]
        assert controls["key_frame"] == "operator" and controls["live"] is None

    def test_the_choice_is_saved_to_the_laptop(self, rig, tmp_path):  # noqa: F811
        rig.session.set_key_frame("room")
        saved = json.loads((tmp_path / "controls.json").read_text())
        assert saved["key_frame"] == "room"
        assert rig.session.snapshot().controls["key_frame"] == "room"

    def test_an_unknown_frame_is_refused_in_words(self, rig):  # noqa: F811
        with pytest.raises(SessionError, match="operator"):
            rig.session.set_key_frame("nose")

    def test_i_am_here_uses_the_drones_position(self, rig):  # noqa: F811
        start_and_confirm(rig)
        position(rig, 0.8, -1.2)
        rig.session.mark_operator(from_drone=True)
        assert rig.session.snapshot().controls["operator"] == [0.8, -1.2]

    def test_i_am_here_without_a_position_says_so(self, rig):  # noqa: F811
        with pytest.raises(SessionError, match="not reporting a position"):
            rig.session.mark_operator(from_drone=True)

    def test_i_am_here_without_base_stations_says_why(self, rig):  # noqa: F811
        start_and_confirm(rig)
        position(rig, 0.8, -1.2)     # dead reckoning reports numbers; they mean nothing
        rig.session.report = SimpleNamespace(assisted=False)
        with pytest.raises(SessionError, match="Without base stations"):
            rig.session.mark_operator(from_drone=True)

    def test_a_spot_outside_any_room_is_refused(self, rig):  # noqa: F811
        with pytest.raises(SessionError, match="not a spot"):
            rig.session.mark_operator(x=500.0, y=0.0)

    def test_a_manual_flight_gets_the_frame_and_the_spot(self, rig):  # noqa: F811
        rig.session.set_key_frame("room")
        rig.session.mark_operator(x=0.5, y=0.25)
        start_and_confirm(rig)
        rig.session.set_mode(Mode.MANUAL)
        rig.session.arm_manual()
        controller = rig.link.manual_controller
        assert controller.key_frame == (KeyFrame.ROOM, (0.5, 0.25))
        assert controller.frame_listener is not None

    def test_what_the_arrows_mean_reaches_the_app(self, rig):  # noqa: F811
        start_and_confirm(rig)
        rig.session.arm_manual()
        listener = rig.link.manual_controller.frame_listener
        listener(FrameStatus(KeyFrame.OPERATOR, ActiveFrame.OPERATOR, None, 30.0,
                             (0.0, 0.0), "takeoff"))
        live = rig.session.snapshot().controls["live"]
        assert live["active"] == "operator" and live["operator_source"] == "takeoff"
        sent = [p for kind, p in rig.events if kind == "session"][-1]
        assert sent["controls"]["live"]["active"] == "operator"
        listener(None)
        assert rig.session.snapshot().controls["live"] is None

    def test_changing_the_frame_in_the_air_reaches_the_controller(self, rig):  # noqa: F811
        start_and_confirm(rig)
        rig.session.arm_manual()
        rig.session.set_key_frame("room")
        assert rig.link.manual_controller.key_frame[0] is KeyFrame.ROOM

    def test_ending_the_session_clears_the_live_frame(self, rig):  # noqa: F811
        start_and_confirm(rig)
        rig.session.arm_manual()
        rig.link.manual_controller.frame_listener(
            FrameStatus(KeyFrame.OPERATOR, ActiveFrame.ROOM, None, 0.0, None, None))
        rig.session.end()
        rig.session.wait_idle()
        assert rig.session.snapshot().controls["live"] is None
