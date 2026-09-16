"""The polling loop.

Almost every test here is a failure case. The happy path is easy; what matters
is that a claimed mission always reaches a terminal state, because one stranded
in `claimed` stops the whole queue and nothing surfaces the fact.
"""

from __future__ import annotations

import contextlib

import pytest

from cropwatcher.flight.missions import hover_mission, lawnmower_mission
from cropwatcher.safety.geofence import Geofence
from cropwatcher.sync.client import ConfigError, QueuedMission, Settings
from cropwatcher.sync.poller import Poller
from tests.test_missions import FakeFlight


class FakeQueue:
    """An in-memory mission queue that records every status change."""

    def __init__(self, missions_to_serve: list[QueuedMission] | None = None):
        self.pending = list(missions_to_serve or [])
        self.statuses: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.claim_calls = 0
        self.released = 0
        self.fail_claim_times = 0

    def claim_next(self):
        self.claim_calls += 1
        if self.fail_claim_times > 0:
            self.fail_claim_times -= 1
            raise ConnectionError("supabase unreachable")
        if not self.pending:
            return None
        mission = self.pending.pop(0)
        self.statuses[mission.id] = "claimed"
        return mission

    def mark_running(self, mission_id, flight_id):
        self.statuses[mission_id] = "running"

    def mark_done(self, mission_id):
        self.statuses[mission_id] = "done"

    def mark_failed(self, mission_id, error):
        self.statuses[mission_id] = "failed"
        self.errors[mission_id] = error

    def release_stale(self):
        return self.released


def queued(mission, mission_id="m1", name="test"):
    return QueuedMission(id=mission_id, name=name, type=str(mission.type),
                         plan=mission.to_dict())


def flight_factory(flight):
    @contextlib.contextmanager
    def factory(_hold_seconds):
        yield flight
    return factory


class TestSettings:
    ALL = ("SUPABASE_URL", "SUPABASE_ANON_KEY",
           "CROPWATCHER_EMAIL", "CROPWATCHER_PASSWORD")

    def _set_all(self, monkeypatch):
        for name in self.ALL:
            monkeypatch.setenv(name, "value")

    def test_missing_variables_are_all_named(self, monkeypatch):
        for name in self.ALL:
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(ConfigError) as e:
            Settings.from_env()
        for name in self.ALL:
            assert name in str(e.value)

    def test_partial_config_names_only_the_missing_one(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CROPWATCHER_PASSWORD", raising=False)
        with pytest.raises(ConfigError) as e:
            Settings.from_env()
        assert "CROPWATCHER_PASSWORD" in str(e.value)
        assert "SUPABASE_URL" not in str(e.value)

    def test_agent_id_defaults_to_the_machine_name(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CROPWATCHER_AGENT_ID", raising=False)
        assert Settings.from_env().agent_id

    def test_service_role_key_is_never_adopted(self, monkeypatch):
        """It must not ship in the installer, so it is warned about and ignored."""
        self._set_all(monkeypatch)
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret")
        settings = Settings.from_env()
        assert settings.anon_key == "value"
        assert "secret" not in (settings.anon_key, settings.password)


class TestHappyPath:
    def test_flies_a_queued_mission_and_marks_it_done(self):
        mission = hover_mission(0.5, 1.0)
        q = FakeQueue([queued(mission)])
        flight = FakeFlight()

        stats = Poller(q, flight_factory(flight)).run_forever(max_iterations=1)

        assert q.statuses["m1"] == "done"
        assert stats.completed == 1
        assert flight.landed

    def test_releases_stale_claims_on_startup(self):
        """A crashed agent must not block its mission forever."""
        q = FakeQueue()
        q.released = 3
        stats = Poller(q, flight_factory(FakeFlight())).run_forever(max_iterations=1)
        assert stats.released == 3

    def test_empty_queue_is_not_an_error(self):
        q = FakeQueue()
        stats = Poller(q, flight_factory(FakeFlight()), idle_poll_s=0.01).run_forever(
            max_iterations=2
        )
        assert stats.claimed == 0
        assert stats.failed == 0


class TestFailurePaths:
    def test_a_malformed_plan_fails_rather_than_looping(self):
        """Retrying cannot fix bad JSON, so it must not go back in the queue."""
        q = FakeQueue([QueuedMission(id="m1", name="bad", type="hover",
                                     plan={"waypoints": [{"x": 1}]})])
        stats = Poller(q, flight_factory(FakeFlight())).run_forever(max_iterations=1)

        assert q.statuses["m1"] == "failed"
        assert "malformed plan" in q.errors["m1"]
        assert stats.rejected == 1

    def test_an_unsafe_plan_is_rejected_before_arming(self):
        mission = lawnmower_mission(20.0, 20.0, 1.0, 0.5)
        q = FakeQueue([queued(mission)])
        flight = FakeFlight()

        poller = Poller(q, flight_factory(flight), geofence=Geofence.square(1.0))
        stats = poller.run_forever(max_iterations=1)

        assert q.statuses["m1"] == "failed"
        assert "safety checks" in q.errors["m1"]
        assert stats.rejected == 1
        # The decisive assertion: nothing ever armed.
        assert flight.calls == []

    def test_a_failing_flight_marks_the_mission_failed(self):
        """Never left in 'claimed' — that stops the queue silently."""
        mission = lawnmower_mission(2.0, 2.0, 1.0, 0.4)
        q = FakeQueue([queued(mission)])
        flight = FakeFlight(fail_at=1)

        stats = Poller(q, flight_factory(flight)).run_forever(max_iterations=1)

        assert q.statuses["m1"] == "failed"
        assert "radio link lost" in q.errors["m1"]
        assert stats.failed == 1

    def test_a_failing_flight_still_lands(self):
        mission = lawnmower_mission(2.0, 2.0, 1.0, 0.4)
        flight = FakeFlight(fail_at=1)
        Poller(FakeQueue([queued(mission)]), flight_factory(flight)).run_forever(
            max_iterations=1
        )
        assert flight.landed

    def test_a_claim_error_does_not_kill_the_loop(self):
        """A transient network failure should back off, not crash the agent."""
        q = FakeQueue([queued(hover_mission(0.5, 1.0))])
        q.fail_claim_times = 1

        poller = Poller(q, flight_factory(FakeFlight()), idle_poll_s=0.01)
        stats = poller.run_forever(max_iterations=3)

        assert stats.completed == 1     # recovered and flew it

    def test_reporting_failure_does_not_lose_the_flight(self):
        """If the flight succeeded but the report failed, that is not a
        mission failure — it is a reporting problem, and must not be counted
        as a crash."""
        mission = hover_mission(0.5, 1.0)
        q = FakeQueue([queued(mission)])

        def explode(_mission_id):
            raise ConnectionError("network died after landing")

        q.mark_done = explode
        flight = FakeFlight()
        stats = Poller(q, flight_factory(flight)).run_forever(max_iterations=1)

        assert flight.landed
        assert stats.failed == 0        # the flight did not fail


class TestTerminalStateInvariant:
    @pytest.mark.parametrize(
        "flight,plan_override",
        [
            (FakeFlight(), None),                                    # success
            (FakeFlight(fail_at=0), None),                           # fails immediately
            (FakeFlight(fail_at=1), None),                           # fails mid-route
            (FakeFlight(critical_after=1), None),                    # aborts on voltage
            (FakeFlight(), {"waypoints": [{"x": "nonsense"}]}),      # malformed
        ],
    )
    def test_every_claimed_mission_reaches_a_terminal_state(self, flight, plan_override):
        """The invariant this whole module exists to protect."""
        mission = lawnmower_mission(2.0, 2.0, 1.0, 0.4)
        plan = plan_override if plan_override is not None else mission.to_dict()
        q = FakeQueue([QueuedMission(id="m1", name="t", type="lawnmower", plan=plan)])

        with contextlib.suppress(Exception):
            Poller(q, flight_factory(flight)).run_forever(max_iterations=1)

        assert q.statuses["m1"] in {"done", "failed"}, (
            f"mission left in {q.statuses['m1']!r} — the queue would stall here"
        )
