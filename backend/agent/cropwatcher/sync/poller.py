"""The polling loop: claim a mission, fly it, report what happened.

The one rule this file exists to enforce: **a claimed mission always reaches a
terminal state.** If the agent claims work and then crashes, throws, or is
interrupted, the mission must end up `done` or `failed` — never left sitting in
`claimed` while the queue quietly stops moving.

Everything here is driven through the :class:`MissionQueue` protocol and a
flight factory, so the loop can be tested without a network or a drone. The
interesting cases are failure cases, and those are hard to provoke on real
hardware.
"""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from cropwatcher.flight import missions
from cropwatcher.flight.core import Flight
from cropwatcher.flight.missions import Mission, MissionValidationError
from cropwatcher.safety.geofence import Geofence
from cropwatcher.safety.occupancy import OccupancyGrid
from cropwatcher.sync.client import MissionQueue, QueuedMission

log = logging.getLogger(__name__)

# Backoff when the queue is empty. Polling hard for an idle greenhouse wastes
# requests all day for no benefit.
IDLE_POLL_S = 3.0
MAX_BACKOFF_S = 30.0

FlightFactory = Callable[[float], AbstractContextManager[Flight]]


@dataclass
class PollerStats:
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    rejected: int = 0
    released: int = 0


class Poller:
    """Claims and flies queued missions until stopped."""

    def __init__(
        self,
        queue: MissionQueue,
        flight_factory: FlightFactory,
        *,
        geofence: Geofence | None = None,
        occupancy: OccupancyGrid | None = None,
        idle_poll_s: float = IDLE_POLL_S,
    ) -> None:
        self._queue = queue
        self._flight_factory = flight_factory
        self._geofence = geofence
        self._occupancy = occupancy
        self._idle_poll_s = idle_poll_s
        self._running = False
        self.stats = PollerStats()

    # ── lifecycle ────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Ask the loop to finish after the current mission."""
        self._running = False

    def install_signal_handlers(self) -> None:
        """Stop cleanly on Ctrl+C rather than abandoning a claimed mission."""
        def handle(signum, _frame):
            log.info("signal %s received, finishing current mission", signum)
            self.stop()

        signal.signal(signal.SIGINT, handle)
        signal.signal(signal.SIGTERM, handle)

    def run_forever(self, max_iterations: int | None = None) -> PollerStats:
        """Poll until stopped. `max_iterations` bounds it for tests."""
        self._running = True
        backoff = self._idle_poll_s
        iterations = 0

        # Reclaim anything a previous run abandoned, so a crashed agent does
        # not permanently block its mission.
        try:
            released = self._queue.release_stale()
            if released:
                self.stats.released += released
                log.info("released %d stale claim(s) from a previous run", released)
        except Exception:
            log.exception("could not release stale claims, continuing")

        while self._running:
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1

            try:
                mission = self._queue.claim_next()
            except Exception:
                log.exception("claim failed, backing off")
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue

            if mission is None:
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue

            backoff = self._idle_poll_s      # work found; reset the backoff
            self.stats.claimed += 1
            self._handle(mission)

        return self.stats

    # ── one mission ──────────────────────────────────────────────────────

    def _handle(self, queued: QueuedMission) -> None:
        """Fly one claimed mission and always report an outcome."""
        log.info("claimed mission %s (%s)", queued.name, queued.id)

        try:
            mission = Mission.from_dict(queued.plan)
        except Exception as e:
            # A malformed plan is permanent: retrying cannot help, so fail it
            # rather than releasing it back into the queue to be reclaimed.
            self._fail(queued, f"malformed plan: {e}")
            self.stats.rejected += 1
            return

        try:
            mission.validate(geofence=self._geofence, occupancy=self._occupancy)
        except MissionValidationError as e:
            self._fail(queued, f"rejected by safety checks: {e}")
            self.stats.rejected += 1
            return

        try:
            self._queue.mark_running(queued.id, None)
            self._fly(mission)
        except Exception as e:
            log.exception("mission %s failed", queued.name)
            self._fail(queued, f"{type(e).__name__}: {e}")
            return

        try:
            self._queue.mark_done(queued.id)
            self.stats.completed += 1
            log.info("mission %s complete", queued.name)
        except Exception:
            # The flight itself succeeded; only the report failed. Say so
            # loudly — the mission will look stuck until someone notices.
            log.exception("flew %s but could not mark it done", queued.name)

    def _fly(self, mission: Mission) -> None:
        with self._flight_factory(mission.estimated_duration_s()) as flight:
            for event in missions.execute(mission, flight):
                log.info("  %s: %s", event.kind, event.detail)

    def _fail(self, queued: QueuedMission, error: str) -> None:
        self.stats.failed += 1
        log.warning("mission %s failed: %s", queued.name, error)
        try:
            self._queue.mark_failed(queued.id, error)
        except Exception:
            # Nothing further we can do; release_stale_claims will eventually
            # return it to the queue rather than leaving it claimed forever.
            log.exception("could not mark %s failed", queued.name)
