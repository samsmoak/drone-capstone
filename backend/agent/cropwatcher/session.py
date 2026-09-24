"""An operating session: one operator, one drone, from sign-in to sign-off.

This is what the desktop app drives, and the only thing that flies a drone.

    sign_in            who is responsible for what follows
    start              connect, then the checks, one step at a time
    confirm_area       the operator says the drone is on the floor and clear
    health_test        the firmware's motor and battery tests (motors spin, briefly)
    retry              after an abnormal end: every check again, same session
    run_program        Auto: a preset flight, e.g. the hover test
    arm_manual         Manual: props idle, then assisted flight from the keys
    land / stop        graceful landing, or the deliberate emergency stop
    end                land if flying, close the flight, upload what is left

Everything long-running happens on a worker thread and reports progress as
events, so the app can show a live checklist instead of a frozen button.

Rules this file exists to hold in one place:

- **Nothing flies until the checks pass and the operator confirms the area.**
- **Nothing flies without a signed-in operator**, so every flight and every
  action has a person attached.
- **Only one activity at a time.** The radio is single-user (a concurrent scan
  produced `[Errno 19] No such device` in the lab).
- **A flight always ends in a landing or a stop**, including when an exception
  escapes: the drone must never be left in the air.
- **After an abnormal end, nothing flies until Retry.** A tumble leaves the
  firmware holding the motors; arming past that is a flight with no thrust.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from cropwatcher.audit import Action, AuditLog, Result
from cropwatcher.flight.checks import CheckResult, ChecksFailed, ReadyReport, collect
from cropwatcher.flight.control import GuardedFlight, PhaseEvent
from cropwatcher.flight.core import DEFAULT_URI
from cropwatcher.flight.link import DEFAULT_FENCE_M, DEFAULT_MAX_HEIGHT_M, DroneLink, LinkError
from cropwatcher.flight.programs import HoverTest, Outcome, run_hover_test
from cropwatcher.history import SessionLog, SessionMeta, sessions_dir
from cropwatcher.paths import flights_dir
from cropwatcher.safety.flight_guard import Action as GuardAction
from cropwatcher.safety.flight_guard import Reason as GuardReason
from cropwatcher.sync import auth_store
from cropwatcher.sync.cloud import AuthError, Cloud, Operator
from cropwatcher.sync.outbox import Kind, Outbox, new_id
from cropwatcher.sync.syncer import Syncer
from cropwatcher.telemetry import trace as flight_trace
from cropwatcher.telemetry.reader import FlightRecorder
from cropwatcher.telemetry.row import TempUnit, parse_ambient
from cropwatcher.telemetry.sinks import CsvSink, FanOutSink, LiveUploadSink

log = logging.getLogger(__name__)

MANUAL_GUARD_PERIOD_S = 0.1

#: How often a signed-in agent with no drone looks for one. NOT faster: polling
#: the radio every 2 s (from /status) wedged the agent with [Errno 19] No such
#: device — sessions-and-modes.txt. It never scans while a link is open.
STANDBY_RETRY_S = 15.0
#: After a drone drops off or a session ends, look again this soon.
STANDBY_SOON_S = 2.0
#: After a restart over the radio, the drone takes ~3 s to answer again
#: (measured 2026-09-24: power-cycle at 1.0 s, link back at 4.6 s). Looking
#: sooner starts a connect that blocks for its full timeout.
RESTART_SETTLE_S = 4.0


def _power_cycle(uri: str) -> None:
    """Restart the drone's electronics through its radio chip (cflib)."""
    from cflib.utils.power_switch import PowerSwitch

    switch = PowerSwitch(uri)
    try:
        switch.stm_power_cycle()
    finally:
        switch.close()


class Mode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class State(StrEnum):
    SIGNED_OUT = "signed_out"
    IDLE = "idle"                               # signed in, no drone session
    STARTING = "starting"                       # connecting and checking
    CHECKS_FAILED = "checks_failed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    READY = "ready"                             # confirmed; may fly
    BUSY = "busy"                               # prop test, program or manual
    ENDING = "ending"


class SessionError(RuntimeError):
    """A refusal the operator should see. Never leaks internals."""


@dataclass
class Snapshot:
    """What the app renders. Serialised straight to JSON."""

    state: State = State.SIGNED_OUT
    # MANUAL, not AUTO. Auto needs `assisted` — a position the drone can hold —
    # and a preset program is refused without it (see run_program below, and
    # flight-safety.txt). Until this room's Lighthouse geometry is measured,
    # every session comes back unassisted, so an Auto default opens the app in
    # the one mode that cannot fly. It also filtered the history: an operator
    # whose flights were all manual saw "no sessions" on every log page with 45
    # readings on disk (2026-09-17).
    #
    # Tests that exercise Auto set the mode explicitly rather than inheriting
    # it, which is what a test about Auto should do anyway.
    mode: Mode = Mode.MANUAL
    operator: dict[str, Any] | None = None
    drone: dict[str, Any] | None = None
    session_id: str | None = None
    activity: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    #: The last battery & motor test (flight/checks.py HealthTestResult).
    health_test: dict[str, Any] | None = None
    flight: dict[str, Any] | None = None
    message: str | None = None
    can_fly: bool = False
    #: True until the saved sign-in has been tried, at startup. The app shows a
    #: loading state while it is set: signed out is not yet known to be true.
    restoring: bool = True
    #: True when the drone can hold a height and a position for itself. False
    #: means the app must offer unassisted manual flight only, and say so.
    assisted: bool = True
    #: Why assistance is unavailable, in words, or None.
    unassisted_reason: str | None = None
    #: Whether the AI deck — the one carrying the camera — is fitted, as the
    #: DRONE reports it (deck.bcAI, over the radio during the checks). None
    #: until a drone has been asked, which is NOT the same as "not fitted".
    #: Recorded and shown; it gates nothing.
    ai_deck: bool | None = None
    #: The radio, apart from any session. "off" (signed out, or not started),
    #: "searching" (no drone found yet — `message` says why), "connected" (a
    #: link is open: vitals stream, the camera gets its network), "paused" (the
    #: operator disconnected, to free the radio for another tool), "restarting"
    #: (restarted over the radio on purpose — restart_drone — back in seconds). A session
    #: takes over a connected link rather than opening a second one.
    radio: dict[str, Any] = field(default_factory=lambda: {
        "state": "off", "hardware_id": None, "message": None})
    #: The last flight ended abnormally — a tumble, a guard, an emergency stop.
    #: Nothing flies until Retry has re-run the checks in this same session:
    #: after a tumble the firmware holds the motors at zero, and a flight armed
    #: into that reports "flying" with nothing turning (2026-09-17).
    retry_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": str(self.state), "mode": str(self.mode), "operator": self.operator,
            "drone": self.drone, "session_id": self.session_id, "activity": self.activity,
            "checks": self.checks, "health_test": self.health_test, "flight": self.flight,
            "message": self.message, "can_fly": self.can_fly, "restoring": self.restoring,
            "assisted": self.assisted, "unassisted_reason": self.unassisted_reason,
            "ai_deck": self.ai_deck,
            "radio": self.radio,
            "retry_required": self.retry_required,
        }


class Session:
    def __init__(
        self,
        *,
        cloud: Cloud,
        outbox: Outbox | None = None,
        syncer: Syncer | None = None,
        link_factory: Callable[[], DroneLink] = DroneLink,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
        agent_id: str = "desktop",
        fence_half_extent_m: float = DEFAULT_FENCE_M,
        max_height_m: float = DEFAULT_MAX_HEIGHT_M,
        on_link_ready: Callable[[Any], object] | None = None,
        on_link_down: Callable[[], object] | None = None,
        on_session_open: Callable[[str, Path], object] | None = None,
        on_session_close: Callable[[], object] | None = None,
        power_cycle: Callable[[str], None] = _power_cycle,
    ) -> None:
        self._cloud = cloud
        #: Called with the Crazyflie once a link has passed its checks and the
        #: AI deck is fitted — how the deck is put on the operator's Wi-Fi. It
        #: runs on its own thread: joining a network takes seconds and must
        #: never hold up a flight.
        self._on_link_ready = on_link_ready
        #: Called whenever the link closes, however — the Wi-Fi state stops
        #: claiming "joined" for a drone nobody can reach any more.
        self._on_link_down = on_link_down
        #: A session opened (its id and folder) / closed — how camera frames
        #: get recorded only inside a session (camera/recording.py).
        self._on_session_open = on_session_open
        self._on_session_close = on_session_close
        self._power_cycle = power_cycle
        self._outbox = outbox or Outbox()
        self._syncer = syncer
        self._link_factory = link_factory
        self._publish = publish
        self._agent_id = agent_id
        self._fence = fence_half_extent_m
        self._max_height = max_height_m

        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        #: What that worker is, and when it started, so a session that will not
        #: free up can say which step is stuck instead of "something".
        self._worker_name: str | None = None
        self._worker_started_at: float | None = None
        self._snapshot = Snapshot()
        self.operator: Operator | None = None
        self.audit: AuditLog | None = None

        self.link: DroneLink | None = None
        self.report: ReadyReport | None = None
        self.flight: GuardedFlight | None = None
        self.manual: Any = None
        self._manual_guard_stop: threading.Event | None = None
        self._recorder: FlightRecorder | None = None
        self._flight_id: str | None = None
        self._unsubscribe_telemetry: Callable[[], None] | None = None
        self.history: SessionLog | None = None
        # The floor, in the estimator frame the current flight is using. The
        # checks' ground unless an unassisted flight re-read it from the baro.
        self._height_reference: float | None = None
        self._manual_lock = threading.Lock()
        self._trace: flight_trace.FlightTrace | None = None
        self._unsubscribe_trace: Callable[[], None] | None = None
        #: Opening and closing `self.link` happen under this, whoever does it —
        #: the standby loop, a session start, a retry, an end. Never held while
        #: waiting on anything but the radio itself.
        self._link_lock = threading.RLock()
        #: The link the Wi-Fi hand-off last ran for, so it runs once per link.
        self._link_ready_for: int | None = None
        self._standby_wake = threading.Event()
        self._standby_stop = threading.Event()
        self._standby_paused = False
        self._standby_thread: threading.Thread | None = None
        #: Standby does not look before this (monotonic): a drone restarting.
        self._standby_not_before = 0.0

    # ── events ───────────────────────────────────────────────────────────

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        if self._publish is not None:
            try:
                self._publish(kind, payload)
            except Exception:
                log.exception("event publish failed")

    def _set(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._snapshot, key, value)
            self._snapshot.can_fly = self._snapshot.state in (State.READY, State.BUSY)
            payload = self._snapshot.to_dict()
        self._emit("session", payload)

    # ── auth ─────────────────────────────────────────────────────────────

    def sign_in(self, email: str, password: str) -> Operator:
        with self._lock:
            if self._snapshot.state not in (State.SIGNED_OUT, State.IDLE):
                raise SessionError("End the current session before signing in again.")
        try:
            operator = self._cloud.sign_in(email, password)
        except AuthError as e:
            raise SessionError(str(e)) from None
        if not operator.is_operator:
            self._cloud.sign_out()
            raise SessionError(
                "This account can view flights but not fly. Ask an operator to change your role."
            )

        self.operator = operator
        self.audit = AuditLog(
            self._outbox, actor_id=operator.id, actor_email=operator.email, source="desktop"
        )
        self.audit.record(Action.SIGN_IN)
        self._remember_sign_in(operator)
        self._signed_in(operator)
        return operator

    def restore_sign_in(self) -> Operator | None:
        """Sign back in from the token saved last time, if there is one.

        Called once at startup. A revoked or expired token is deleted and the
        app shows the sign-in form, exactly as if nothing had been saved.
        """
        with self._lock:
            if self._snapshot.state is not State.SIGNED_OUT:
                self._snapshot.restoring = False
                return self.operator
        stored = auth_store.load()
        restore = getattr(self._cloud, "restore", None)
        if stored is None or restore is None:
            self._set(restoring=False)
            return None
        token, _email = stored
        try:
            operator: Operator = restore(token)
        except AuthError as e:
            auth_store.clear()
            self._set(message=str(e), restoring=False)
            return None
        if not operator.is_operator:
            auth_store.clear()
            self._cloud.sign_out()
            self._set(restoring=False)
            return None
        self.operator = operator
        self.audit = AuditLog(
            self._outbox, actor_id=operator.id, actor_email=operator.email, source="desktop"
        )
        self.audit.record(Action.SIGN_IN, detail={"restored": True})
        self._remember_sign_in(operator)       # refresh tokens rotate on use
        self._signed_in(operator)
        return operator

    def _remember_sign_in(self, operator: Operator) -> None:
        token = getattr(self._cloud, "refresh_token", None)
        if isinstance(token, str) and token:
            try:
                auth_store.save(token, operator.email)
            except OSError:
                log.warning("could not save the sign-in; the next launch will ask again")

    def _signed_in(self, operator: Operator) -> None:
        self._set(
            restoring=False,
            state=State.IDLE,
            operator={"id": operator.id, "email": operator.email, "name": operator.full_name,
                      "role": operator.role},
            message=None,
        )
        if self._syncer is not None:
            self._syncer.trigger()
        self._wake_standby(0)

    def sign_out(self) -> None:
        if self.snapshot().state not in (State.SIGNED_OUT, State.IDLE):
            self.end("signed out")
        # A drone held on standby is released: no one is signed in to see it.
        if self.snapshot().state == State.IDLE:
            self._close_link()
        if self.audit is not None:
            self.audit.record(Action.SIGN_OUT)
        if self._syncer is not None:
            self._syncer.trigger()
        self._cloud.sign_out()
        auth_store.clear()
        self.operator, self.audit = None, None
        self._set(state=State.SIGNED_OUT, operator=None, message=None, restoring=False,
                  radio={"state": "off", "hardware_id": None, "message": None})

    def _require_operator(self) -> tuple[Operator, AuditLog]:
        if self.operator is None or self.audit is None:
            raise SessionError("Sign in before operating the drone.")
        return self.operator, self.audit

    # ── mode ─────────────────────────────────────────────────────────────

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            if self._snapshot.state is State.BUSY:
                raise SessionError("Finish the current flight before switching mode.")
            previous = self._snapshot.mode
        if previous is mode:
            return
        self._set(mode=mode)
        if self.history is not None:
            self.history.set_mode(str(mode))
        if self.audit is not None:
            self.audit.record(Action.MODE_CHANGED, detail={"from": str(previous), "to": str(mode)},
                              session_id=self._snapshot.session_id)

    # ── worker ───────────────────────────────────────────────────────────

    def _start_worker(self, name: str, work: Callable[[], None]) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                # Name what is running and for how long. "Something is already
                # running" was true and useless on 2026-09-22: a connect that
                # could not time out held this for ever, and the operator was
                # told to wait for a thing the message would not name.
                busy, since = self._worker_name, self._worker_started_at
                waited = f" for {time.monotonic() - since:.0f}s" if since else ""
                raise SessionError(
                    f"{busy or 'Something'} is still running{waited}. Wait for it to "
                    f"finish, or press End session to stop it."
                )

            def run() -> None:
                try:
                    work()
                except SessionError as e:
                    self._set(message=str(e))
                except Exception:
                    log.exception("%s failed", name)
                    self._set(message="Something went wrong. The log has the details.")

            self._worker_name = name.replace("_", " ").capitalize()
            self._worker_started_at = time.monotonic()
            self._worker = threading.Thread(target=run, daemon=True, name=f"session-{name}")
            self._worker.start()

    def wait_idle(self, timeout: float = 30.0) -> None:
        """For tests and for End session: wait for the current activity."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    # ── start: connect and check ─────────────────────────────────────────

    def start(self) -> None:
        self._require_operator()
        with self._lock:
            if self._snapshot.state not in (State.IDLE, State.CHECKS_FAILED):
                raise SessionError("A session is already running.")
            if self._snapshot.session_id is not None:
                raise SessionError("This session is still open. Press Retry to check the "
                                   "drone again, or end the session first.")
        self._set(state=State.STARTING, checks=[], message=None, health_test=None)
        self._start_worker("start", self._do_start)

    def _do_start(self) -> None:
        operator, audit = self._require_operator()
        session_id = new_id()
        report = self._connect_and_check(audit, on_refused=lambda detail: audit.record(
            Action.SESSION_START, Result.REFUSED, detail=detail))
        if report is None:
            return
        link = self.link
        assert link is not None

        self.report = report
        self._outbox.put(Kind.DRONE, report.hardware_id, {
            "hardware_id": report.hardware_id, "name": report.hardware_id, "uri": link.uri,
        })
        self._outbox.put(Kind.SESSION, session_id, {
            "id": session_id, "drone_hardware_id": report.hardware_id,
            "operator_id": operator.id, "agent_id": self._agent_id,
            "mode_at_start": str(self.snapshot().mode),
            "started_at": datetime.now(UTC).isoformat(), "ended_at": None,
        })
        audit.record(Action.SESSION_START, session_id=session_id,
                     drone_hardware_id=report.hardware_id)
        self._height_reference = report.ground_z_m if report.assisted else None
        try:
            self.history = SessionLog(
                SessionMeta(
                    id=session_id, operator_id=operator.id, operator_email=operator.email,
                    operator_name=operator.full_name, drone_hardware_id=report.hardware_id,
                    mode=str(self.snapshot().mode), assisted=report.assisted,
                    started_at=datetime.now(UTC).isoformat(),
                ),
                height_reference=lambda: self._height_reference,
            )
        except OSError:
            log.exception("could not open the session history; flying without it")
            self.history = None
        if self._on_session_open is not None:
            folder = (self.history.folder if self.history is not None
                      else sessions_dir() / session_id)
            try:
                self._on_session_open(session_id, folder)
            except Exception:
                log.exception("session-open hook failed; the session carries on")
        self._set(
            state=State.AWAITING_CONFIRMATION, session_id=session_id,
            drone={"hardware_id": report.hardware_id, "battery_v": round(report.vbat, 2),
                   "endurance_s": round(report.endurance_s)},
            assisted=report.assisted,
            unassisted_reason=report.unassisted_reason,
            ai_deck=report.ai_deck,
            message=(
                "Put the drone on a flat, clear surface, then confirm."
                if report.assisted else
                "The drone cannot hold a height by itself right now. Put it on a flat, "
                "clear surface, then confirm to fly it by hand."
            ),
        )
        if self._syncer is not None:
            self._syncer.trigger()

    def _connect_and_check(
        self, audit: AuditLog, *, on_refused: Callable[[dict[str, Any]], object]
    ) -> ReadyReport | None:
        """Open the link if it is not open, then run every check.

        The one path a new session and a retry both take — so a retry is the
        same steps as starting afresh, not a shortcut past them. On any failure
        the link is closed (a power-cycled drone needs a fresh one) and the
        state says why; the caller gets None.
        """
        steps: list[dict[str, Any]] = []

        def on_step(step: CheckResult) -> None:
            nonlocal steps
            steps = [s for s in steps if s["key"] != str(step.key)] + [step.to_dict()]
            self._set(checks=steps)

        with self._link_lock:
            link = self.link
            if link is None or not link.is_open:
                # No standby link to take over: open one. (With standby
                # running, the session usually inherits the link it opened.)
                try:
                    link = self._link_factory()
                    link.open()
                    self.link = link
                except LinkError as e:
                    on_refused({"reason": str(e)})
                    self._set(state=State.CHECKS_FAILED, message=str(e),
                              radio={"state": "searching", "hardware_id": None,
                                     "message": str(e)})
                    return None
                # Live telemetry reaches the app's windows from the moment the
                # link is open — before, during and after a flight.
                if link.stream is not None:
                    self._unsubscribe_telemetry = link.stream.subscribe(self._publish_telemetry)

        try:
            report = collect(link.checks(), on_step)
        except ChecksFailed as e:
            audit.record(Action.CHECKS, Result.REFUSED, session_id=self._snapshot.session_id,
                         detail={"check": str(e.result.key), "reason": e.result.detail})
            self._close_link()
            self._set(state=State.CHECKS_FAILED, message=e.result.detail)
            return None

        # The geofence is centred on the Lighthouse origin; a drone parked
        # outside it would be landed by the guard the moment it took off.
        # Unassisted there is no origin and no fence — those coordinates are the
        # accelerometer integrating — so there is nothing to compare against.
        x, y = report.takeoff_xy
        if report.assisted and max(abs(x), abs(y)) > self._fence:
            message = (
                f"The drone is at ({x:+.2f}, {y:+.2f}) m, outside the {self._fence:.1f} m "
                f"flight area. Move it nearer the middle of the room."
            )
            audit.record(Action.CHECKS, Result.REFUSED, session_id=self._snapshot.session_id,
                         detail={"reason": "outside_fence"})
            self._close_link()
            self._set(state=State.CHECKS_FAILED, message=message)
            return None
        self._set(radio={"state": "connected", "hardware_id": report.hardware_id,
                         "message": None})
        self._link_ready(link, report.ai_deck)
        return report

    def _link_ready(self, link: DroneLink, ai_deck: bool | None) -> None:
        """Hand the link to the Wi-Fi hand-off, once per link."""
        hook = self._on_link_ready
        if hook is None or not ai_deck or self._link_ready_for == id(link):
            return
        camera_cf = getattr(link, "camera_cf", None)
        cf = camera_cf() if camera_cf is not None else None
        if cf is None:
            return
        self._link_ready_for = id(link)

        def run() -> None:
            try:
                hook(cf)
            except Exception:
                log.exception("link-ready hook failed")

        threading.Thread(target=run, name="link-ready", daemon=True).start()

    # ── retry ────────────────────────────────────────────────────────────

    def retry(self) -> None:
        """Check the drone again in this same session, as if it were new.

        After a crash: recover the motors, run every check, ask for the area to
        be confirmed again. The session, its history and its audit trail carry
        on — the operator does not lose the record of what happened.
        """
        self._require_operator()
        with self._lock:
            snap = self._snapshot
            if snap.session_id is None:
                raise SessionError("There is no session to retry. Start one.")
            if snap.state not in (State.READY, State.CHECKS_FAILED, State.AWAITING_CONFIRMATION):
                raise SessionError("Wait for the drone to land before retrying.")
        self._set(state=State.STARTING, checks=[], health_test=None, flight=None,
                  message="Checking the drone again, as for a new session.")
        self._start_worker("retry", self._do_retry)

    def _do_retry(self) -> None:
        _, audit = self._require_operator()
        session_id = self._snapshot.session_id
        was_required = self._snapshot.retry_required
        audit.record(Action.SESSION_RETRY, session_id=session_id,
                     detail={"after_abnormal_end": was_required})
        report = self._connect_and_check(audit, on_refused=lambda detail: audit.record(
            Action.SESSION_RETRY, Result.REFUSED, session_id=session_id, detail=detail))
        if report is None:
            return                                  # still retry_required; Retry again
        self.report = report
        self._height_reference = report.ground_z_m if report.assisted else None
        self._set(
            state=State.AWAITING_CONFIRMATION, retry_required=False,
            drone={"hardware_id": report.hardware_id, "battery_v": round(report.vbat, 2),
                   "endurance_s": round(report.endurance_s)},
            assisted=report.assisted, unassisted_reason=report.unassisted_reason,
            ai_deck=report.ai_deck,
            message=(
                "Checked again. Put the drone on a flat, clear surface, then confirm."
                if report.assisted else
                "Checked again. The drone cannot hold a height by itself right now — put it "
                "on a flat, clear surface, then confirm to fly it by hand."
            ),
        )

    def _publish_telemetry(self, snap: Any) -> None:
        ground = self._height_reference
        z = snap.get("stateEstimate.z")
        self._emit("telemetry", {
            "values": dict(snap.values),
            # No height without a reference: unassisted, before the barometer
            # ground is read, the Kalman z is noise and is not shown as height.
            "height_m": None if z is None or ground is None else round(z - ground, 3),
            "at": time.time(),
        })
        history = self.history
        if history is not None:
            try:
                history.sample(snap)
            except OSError:
                log.warning("could not write a history sample")

    # ── confirmation ─────────────────────────────────────────────────────

    def confirm_area(self, accept_unassisted: bool = False) -> None:
        """The operator confirms the area — and, when the drone cannot help
        itself, that they are taking the height and the position on themselves.

        The second acknowledgement is not paperwork. Without a position
        estimate the drone holds nothing, the drift and altitude guards cannot
        run, and Land is a throttle ramp rather than a descent. Whoever is
        standing over the drone gets to decide that, having been told it.
        """
        _, audit = self._require_operator()
        with self._lock:
            if self._snapshot.state is not State.AWAITING_CONFIRMATION:
                raise SessionError("Run the checks first.")
        report = self._require_report()
        if not report.assisted and not accept_unassisted:
            raise SessionError(
                "The drone cannot hold a height or a position right now, so it will "
                "only fly unassisted — you control the throttle and the drone will not "
                "catch itself. Confirm that you are flying it by eye to continue."
            )
        audit.record(Action.AREA_CONFIRMED, session_id=self._snapshot.session_id,
                     detail={"assisted": report.assisted})
        self._set(state=State.READY, message=None)

    # ── battery & motor test ─────────────────────────────────────────────

    def health_test(self) -> None:
        self._require_ready("the battery & motor test")
        self._set(state=State.BUSY, activity="health_test", message=None)
        self._start_worker("health-test", self._do_health_test)

    #: The old name, for an app build that still calls it.
    prop_test = health_test

    def _do_health_test(self) -> None:
        _, audit = self._require_operator()
        link = self._require_link()
        try:
            result = link.health_test()
        except Exception as e:
            audit.record(Action.HEALTH_TEST, Result.FAILED, session_id=self._snapshot.session_id,
                         detail={"error": type(e).__name__})
            self._set(state=State.READY, activity=None,
                      message="The battery & motor test did not report a result.")
            return
        audit.record(Action.HEALTH_TEST, Result.OK if result.ok else Result.FAILED,
                     session_id=self._snapshot.session_id, detail=result.to_dict())
        problems = []
        if result.motors.failed:
            problems.append(f"Motor(s) {', '.join(str(m) for m in result.motors.failed)} did not "
                            f"pass — check for a bent or loose propeller.")
        if result.battery is None:
            problems.append(result.battery_error or "The battery test did not report.")
        elif not result.battery.passed:
            problems.append(f"The battery sagged {result.battery.sag_v:.2f} V under load, more "
                            f"than the drone accepts — charge it or use another battery.")
        self._set(state=State.READY, activity=None, health_test=result.to_dict(),
                  message=" ".join(problems) or None)

    # ── auto: programs ───────────────────────────────────────────────────

    def run_program(
        self, height_m: float = 0.30, hold_s: float = 10.0, ambient: str = "22C"
    ) -> None:
        self._require_ready("a program")
        if self.snapshot().mode is not Mode.AUTO:
            raise SessionError("Switch to Auto to run a program.")
        # A preset program flies itself to a height and holds it. With no
        # position estimate there is no height to fly to and nothing to hold
        # with — this is the exact state that put a drone into a wall on
        # 2026-09-16. Manual stays available: there the operator is the loop.
        if not self._require_report().assisted:
            raise SessionError(
                "A program needs the drone to know where it is, and it does not right "
                "now — it would fly blind. Switch to Manual to fly it by hand, or get "
                "the base stations seen and run the checks again."
            )
        try:
            program = HoverTest(height_m=height_m, hold_s=hold_s)
        except ValueError as e:
            raise SessionError(str(e)) from None
        report = self._require_report()
        if program.duration_s() > report.budget_s():
            raise SessionError(
                f"This battery has about {report.budget_s():.0f} s of flying left, and the "
                f"program needs {program.duration_s():.0f} s. Charge or shorten the hold."
            )
        self._set(state=State.BUSY, activity="program", message=None)
        self._start_worker("program", lambda: self._do_program(program, ambient))

    def _do_program(self, program: HoverTest, ambient: str) -> None:
        _, audit = self._require_operator()
        link, report = self._require_link(), self._require_report()
        flight_id = self._begin_flight(mode=Mode.AUTO, program=program.key, ambient=ambient)

        def on_phase(event: PhaseEvent) -> None:
            self._set(flight={"id": flight_id, "phase": str(event.phase), "detail": event.detail})

        flight = link.guarded_flight(
            report, target_height_m=program.height_m,
            fence_half_extent_m=self._fence, max_height_m=self._max_height, on_phase=on_phase,
        )
        self.flight = flight
        try:
            result = run_hover_test(flight, program)
        except Exception as e:
            self._finish_flight(status="failed", error=f"{type(e).__name__}: {e}")
            audit.record(Action.PROGRAM_RUN, Result.FAILED, session_id=self._snapshot.session_id,
                         flight_id=flight_id, detail={"program": program.key})
            self._set(state=State.READY, activity=None, retry_required=True,
                      message="The flight failed. Press Retry to check the drone again "
                              "before flying.")
            return
        finally:
            self.flight = None

        self._finish_flight(
            status="completed" if result.outcome is Outcome.COMPLETED else "aborted",
            outcome=str(result.outcome), abort_reason=str(result.reason),
        )
        audit.record(
            Action.PROGRAM_RUN,
            Result.OK if result.outcome is Outcome.COMPLETED else Result.ABORTED,
            session_id=self._snapshot.session_id, flight_id=flight_id,
            detail={"program": program.key, **result.to_dict()},
        )
        completed = result.outcome is Outcome.COMPLETED
        self._set(state=State.READY, activity=None, retry_required=not completed,
                  message=result.message if completed else
                  f"{result.message} Press Retry to check the drone again before flying.")

    # ── manual ───────────────────────────────────────────────────────────

    def arm_manual(self, ambient: str = "22C") -> None:
        self._require_ready("manual control")
        if self.snapshot().mode is not Mode.MANUAL:
            raise SessionError("Switch to Manual to fly by hand.")
        _, audit = self._require_operator()
        link, report = self._require_link(), self._require_report()

        flight_id = self._begin_flight(mode=Mode.MANUAL, program=None, ambient=ambient)
        controller = link.manual(report)
        self._height_reference = controller.ground_z
        applied = [a.to_dict() for a in getattr(link, "tuning_applied", [])]
        self._start_trace(link, controller, flight_id, applied)
        controller.arm()
        controller.start()
        self.manual = controller
        audit.record(Action.MANUAL_ARM, session_id=self._snapshot.session_id, flight_id=flight_id,
                     detail={"tuning": applied, "assisted": report.assisted})
        self._start_manual_guard()
        self._set(state=State.BUSY, activity="manual",
                  message=(
                      "Props are turning. Hold W to rise gently."
                      if report.assisted else
                      "Unassisted: props are idling. Hold W to raise the throttle until it "
                      "lifts; let go and the throttle stays put — you hold the height."
                  ))

    def hold_manual(self, height_m: float = 0.30) -> None:
        """Rise to a height and hold it, in Manual, without holding W.

        This is NOT the Auto hover test. That one is a preset program that
        flies itself and needs a position estimate to fly to (run_program
        refuses without one). This asks the manual controller for the same
        climb the W key asks for, and then stops asking — so it works
        unassisted, on the barometer, which is the state this drone is
        usually in.

        The operator stays in the loop throughout: W and S cancel it on the
        next tick, Land still lands, and every guard and the heartbeat
        dead-man are untouched.
        """
        controller = self.manual
        if controller is None or self._snapshot.activity != "manual":
            raise SessionError("Start the motors first.")
        try:
            controller.hold_at(height_m)
        except (RuntimeError, ValueError) as e:
            raise SessionError(str(e)) from None
        self._set(message=f"Rising to {height_m:.2f} m and holding. W or S takes over.")

    def _start_trace(self, link: Any, controller: Any, flight_id: str, applied: list[dict]) -> None:
        """A 10 Hz control trace beside the flight CSV (telemetry/trace.py)."""
        stream = getattr(link, "stream", None)
        if stream is None:
            return
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            path = flights_dir() / day / f"trace_{flight_id[:8]}.csv"
            tuning = ";".join(f"{a['name']}={a['before']}->{a['after']}" for a in applied)
            self._trace = flight_trace.FlightTrace(path, controller, tuning=tuning)
            self._unsubscribe_trace = flight_trace.subscribe(stream, self._trace)
        except OSError:
            log.exception("could not start the flight trace; flying without it")
            self._trace = None

    def _stop_trace(self) -> None:
        if self._unsubscribe_trace is not None:
            try:
                self._unsubscribe_trace()
            except Exception:
                log.debug("trace unsubscribe failed")
            self._unsubscribe_trace = None
        if self._trace is not None:
            self._trace.close()
            self._trace = None

    def set_intent(self, keys: dict[str, Any]) -> None:
        if self.manual is None:
            return
        from cropwatcher.flight.manual import Intent

        self.manual.set_intent(Intent.from_payload(keys))

    def heartbeat(self) -> None:
        if self.manual is not None:
            self.manual.heartbeat()

    def _start_manual_guard(self) -> None:
        """Manual flight is watched too — the operator steers, the guard still
        ends the flight on low battery, lost positioning or the geofence."""
        link, report = self._require_link(), self._require_report()
        guard = link.manual_guard(
            report, fence_half_extent_m=self._fence, max_height_m=self._max_height
        )
        stop = threading.Event()
        self._manual_guard_stop = stop

        def watch() -> None:
            verdict_seen: Any = None
            while not stop.wait(MANUAL_GUARD_PERIOD_S):
                controller = self.manual
                if controller is None:
                    return
                state = str(controller.state)
                # Whatever ended it — Land, S to the floor, the heartbeat, a
                # guard, Emergency stop — a finished flight gives the session
                # back. Before this, a tumble left the app "busy" for good:
                # no End, no mode switch, no second attempt.
                if state in ("landed", "stopped", "idle"):
                    self._finish_manual(controller, verdict_seen)
                    return
                if verdict_seen is not None or state not in ("armed", "flying"):
                    continue
                verdict = guard.check(link.snapshot(), time.monotonic())
                if verdict.ok:
                    continue
                verdict_seen = verdict
                if self.audit is not None:
                    self.audit.record(
                        Action.GUARD_ABORT, Result.ABORTED,
                        session_id=self._snapshot.session_id, flight_id=self._flight_id,
                        detail={"reason": str(verdict.reason), "action": str(verdict.action)},
                    )
                if verdict.action is GuardAction.STOP:
                    controller.emergency_stop()
                else:
                    controller.land()
                self._set(message=verdict.message)

        threading.Thread(target=watch, daemon=True, name="manual-guard").start()

    def _finish_manual(self, controller: Any, verdict: Any) -> None:
        """Close a manual flight that has come down, and free the session."""
        with self._manual_lock:
            if self.manual is not controller:
                return                      # End session got there first
            self.manual = None
        try:
            controller.stop()
        except Exception:
            log.exception("manual loop did not stop cleanly")
        if self._manual_guard_stop is not None:
            self._manual_guard_stop.set()
            self._manual_guard_stop = None
        self._stop_trace()
        report = self.report
        if self.link is not None:
            self.link.restore_estimator()        # tuning back, Kalman back
        if report is not None:
            self._height_reference = report.ground_z_m if report.assisted else None

        stopped = str(controller.state) == "stopped"
        reason = str(verdict.reason) if verdict is not None else None
        self._finish_flight(
            status="aborted" if (verdict is not None or stopped) else "completed",
            outcome="aborted" if (verdict is not None or stopped) else "landed",
            abort_reason=reason or ("emergency_stop" if stopped else None),
        )

        if verdict is not None and verdict.reason is GuardReason.BATTERY_LOW:
            # Low battery ends the operation, not just the flight: another
            # takeoff on this charge is the thing being prevented.
            self._set(state=State.READY, activity=None)
            self.end("battery_low")
            self._set(message="The battery ran low, so the drone landed and the session ended. "
                              "Charge or swap the battery, then start a new session.")
            return
        abnormal = verdict is not None or stopped
        message = (
            verdict.message + " The flight ended early — press Retry to check the drone "
            "again before flying." if verdict is not None else
            "Motors stopped. Check the drone, then press Retry to run the checks again."
            if stopped else
            "Landed. Fly again, or end the session."
        )
        self._set(state=State.READY, activity=None, flight=None,
                  retry_required=abnormal, message=message)

    # ── land and stop ────────────────────────────────────────────────────

    def land(self) -> None:
        _, audit = self._require_operator()
        audit.record(Action.LAND, session_id=self._snapshot.session_id, flight_id=self._flight_id)
        if self.manual is not None:
            self.manual.land()
        elif self.flight is not None:
            self.flight.request_land()
        self._set(message="Landing.")

    def emergency_stop(self) -> None:
        _, audit = self._require_operator()
        audit.record(Action.EMERGENCY_STOP, Result.ABORTED,
                     session_id=self._snapshot.session_id, flight_id=self._flight_id)
        if self.manual is not None:
            self.manual.emergency_stop()
        if self.flight is not None:
            self.flight.request_stop()
        self._set(message="Motors stopped.")

    # ── end ──────────────────────────────────────────────────────────────

    def end(self, reason: str = "operator") -> None:
        with self._lock:
            if self._snapshot.state in (State.SIGNED_OUT, State.IDLE):
                return
        self._set(state=State.ENDING, activity="ending",
                  message="Landing if needed, then saving this session's data.")
        self._do_end(reason)

    def _do_end(self, reason: str) -> None:
        # Land first, whatever else fails afterwards.
        with self._manual_lock:
            manual, self.manual = self.manual, None
        try:
            if manual is not None:
                manual.stop()                    # lands if airborne, then disarms
            elif self.flight is not None:
                self.flight.request_land()
                self.wait_idle(timeout=15.0)
        except Exception:
            log.exception("landing during End session failed — stopping the motors")
            if manual is not None:
                manual.emergency_stop()
            elif self.flight is not None:
                self.flight.request_stop()

        if self._manual_guard_stop is not None:
            self._manual_guard_stop.set()
            self._manual_guard_stop = None
        self._stop_trace()
        if manual is not None and self.link:
            self.link.restore_estimator()        # tuning back, Kalman back
        self.flight = None

        if self._flight_id is not None:
            self._finish_flight(status="completed", outcome="ended_with_session")
        if self.history is not None:
            try:
                self.history.close(reason)
            except OSError:
                log.warning("could not close the session history")
            self.history = None
        if self._on_session_close is not None:
            try:
                self._on_session_close()
            except Exception:
                log.exception("session-close hook failed")
        self._height_reference = None

        session_id = self._snapshot.session_id
        if session_id is not None:
            self._outbox.update(Kind.SESSION, session_id, lambda p: p.update({
                "ended_at": datetime.now(UTC).isoformat(), "end_reason": reason,
            }))
        if self.audit is not None:
            self.audit.record(Action.SESSION_END, session_id=session_id, detail={"reason": reason})

        self._close_link()
        self.report = None
        if self._syncer is not None:
            self._syncer.trigger()
        self._set(state=State.IDLE, activity=None, session_id=None, drone=None, checks=[],
                  health_test=None, flight=None, assisted=True, unassisted_reason=None,
                  retry_required=False,
                  radio=self._radio_idle(),
                  message="Session ended. Data is uploading in the background.")

    def position(self) -> tuple[float, float, float] | None:
        """The drone's position estimate now, or None — for tagging frames."""
        link = self.link
        if link is None or not link.is_open:
            return None
        try:
            snap = link.snapshot()
        except Exception:
            return None
        xyz = (snap.get("stateEstimate.x"), snap.get("stateEstimate.y"),
               snap.get("stateEstimate.z"))
        if any(v is None for v in xyz):
            return None
        return (float(xyz[0]), float(xyz[1]), float(xyz[2]))  # type: ignore[arg-type]

    # ── standby: the drone connected with no session ─────────────────────
    #
    # Signed in and idle, the agent holds a link to the drone so the operator
    # sees its vitals and its camera before starting anything. A standby link
    # NEVER arms: nothing here commands the motors, every flight command still
    # requires a session, and a session that takes the link over runs every
    # check exactly as if it had opened the link itself. Nothing is recorded:
    # telemetry reaches a file only through a session's history.

    def start_standby(self) -> None:
        """Begin looking for the drone. Idempotent; called once by the agent."""
        if self._standby_thread is not None:
            return
        self._standby_stop.clear()
        self._standby_thread = threading.Thread(
            target=self._standby_loop, name="standby", daemon=True)
        self._standby_thread.start()
        self._wake_standby(0)

    def stop_standby(self) -> None:
        self._standby_stop.set()
        self._standby_wake.set()

    def connect_drone(self) -> None:
        """The operator's Connect: look now, and keep looking."""
        self._require_operator()
        self._standby_paused = False
        self._set(radio={"state": "searching", "hardware_id": None,
                         "message": "Looking for the drone…"})
        self._wake_standby(0)

    def disconnect_drone(self) -> None:
        """The operator's Disconnect: release the radio until Connect.

        So another tool (a flasher, the CLI) can use it. Refused mid-session —
        End session is how a session lets go of the drone.
        """
        self._require_operator()
        if self.snapshot().state != State.IDLE:
            raise SessionError("End the session first — it is using the drone.")
        self._standby_paused = True
        self._close_link()
        self._set(radio={"state": "paused", "hardware_id": None,
                         "message": "Disconnected. The radio is free for other tools."})

    def restart_drone(self, *, reason: str) -> None:
        """Restart the drone's electronics over the radio — BETWEEN SESSIONS ONLY.

        The one supported way to make the AI deck rejoin Wi-Fi and announce its
        address again. Resetting only the deck was tried and does not work: the
        STM32's UART link to the ESP32 syncs once, at boot ("There's no support
        for re-initializing the UART transport" — cpx_uart_transport.c). A
        restart runs that boot, and standby reconnects: measured 2026-09-24 at
        4.6 s to the radio, 12.1 s to the first frame.

        Refused unless idle: a session's checks describe the drone as it is, and
        a restart in the air drops it.
        """
        self._require_operator()
        if self.snapshot().state != State.IDLE:
            raise SessionError("A session is using the drone. End it first.")
        with self._link_lock:
            uri = self.link.uri if self.link is not None else DEFAULT_URI
            self._close_link()
            self._standby_not_before = time.monotonic() + RESTART_SETTLE_S
            try:
                self._power_cycle(uri)
            except Exception as e:
                log.warning("restart over the radio failed: %s", e)
                self._set(radio={"state": "searching", "hardware_id": None,
                                 "message": "Could not restart the drone over the radio."})
                return
        log.info("restarted the drone: %s", reason)
        self._set(radio={"state": "restarting", "hardware_id": None,
                         "message": "Restarting the drone…"})
        self._wake_standby(RESTART_SETTLE_S)

    def _wake_standby(self, after_s: float) -> None:
        if after_s <= 0:
            self._standby_wake.set()
        else:
            timer = threading.Timer(after_s, self._standby_wake.set)
            timer.daemon = True
            timer.start()

    def _radio_idle(self) -> dict[str, Any]:
        if self._standby_paused:
            return {"state": "paused", "hardware_id": None,
                    "message": "Disconnected. The radio is free for other tools."}
        return {"state": "searching", "hardware_id": None, "message": "Looking for the drone…"}

    def _standby_loop(self) -> None:
        while not self._standby_stop.is_set():
            self._standby_wake.wait(STANDBY_RETRY_S)
            self._standby_wake.clear()
            if self._standby_stop.is_set():
                return
            try:
                self._standby_tick()
            except Exception:
                log.exception("standby: unexpected failure; will look again")

    def _standby_tick(self) -> None:
        """One look for the drone, when — and only when — standby may hold it."""
        snap = self.snapshot()
        if snap.state != State.IDLE or self.operator is None or self._standby_paused:
            return                                   # a session owns the radio, or no one
        if time.monotonic() < self._standby_not_before:
            return                                   # the drone is still restarting
        with self._link_lock:
            if self.link is not None and self.link.is_open:
                return                               # already connected
            if self.snapshot().state != State.IDLE:
                return                               # a session started meanwhile
            link = self._link_factory()
            try:
                link.open()
            except LinkError as e:
                self._set(radio={"state": "searching", "hardware_id": None,
                                 "message": str(e)})
                return
            self.link = link
            if link.stream is not None:
                self._unsubscribe_telemetry = link.stream.subscribe(self._publish_telemetry)
        try:
            hardware_id, ai_deck = link.identify()
        except Exception:
            log.warning("standby: could not identify the drone")
            hardware_id, ai_deck = None, None
        link.on_lost(lambda reason: self._standby_lost(link, reason))
        self._set(ai_deck=ai_deck, radio={"state": "connected", "hardware_id": hardware_id,
                                          "message": None})
        log.info("standby: connected to %s", hardware_id or link.uri)
        self._link_ready(link, ai_deck)

    def _standby_lost(self, link: DroneLink, reason: str) -> None:
        """cflib's thread: record it, and let another thread close the link."""
        def drop() -> None:
            with self._link_lock:
                if self.link is not link:
                    return                           # already replaced or closed
                if self.snapshot().state != State.IDLE:
                    # A session owns this link; its own guards handle a loss.
                    # The radio state is still worth showing.
                    self._set(radio={"state": "searching", "hardware_id": None,
                                     "message": f"The drone's radio link dropped ({reason})."})
                    return
                self._close_link()
            self._set(radio={"state": "searching", "hardware_id": None,
                             "message": f"The drone disconnected ({reason}). Looking again…"})

        threading.Thread(target=drop, name="standby-lost", daemon=True).start()

    # ── flight records ───────────────────────────────────────────────────

    def _begin_flight(self, *, mode: Mode, program: str | None, ambient: str) -> str:
        link, report = self._require_link(), self._require_report()
        try:
            ambient_c, unit = parse_ambient(ambient)
        except ValueError as e:
            raise SessionError(str(e)) from None

        flight_id = new_id()
        csv_sink = CsvSink(root=flights_dir(), prefix=f"flight_{flight_id[:8]}")
        sinks: list[Any] = [csv_sink]
        if hasattr(self._cloud, "insert_telemetry"):
            sinks.append(LiveUploadSink(self._cloud.insert_telemetry))

        stream = link.stream
        assert stream is not None
        recorder = FlightRecorder(
            stream, FanOutSink(sinks), ambient_c=ambient_c, unit=unit,
            ground_z=report.ground_z_m, flight_id=flight_id,
        )
        recorder.start()
        self._recorder, self._flight_id = recorder, flight_id

        self._outbox.put(Kind.FLIGHT, flight_id, {
            "id": flight_id, "session_id": self._snapshot.session_id,
            "drone_hardware_id": report.hardware_id,
            "created_by": self.operator.id if self.operator else None,
            "started_at": datetime.now(UTC).isoformat(), "ended_at": None,
            "status": "running", "mode": str(mode), "program": program,
            "temp_unit": str(unit), "ambient_start": round(ambient_c if unit is TempUnit.CELSIUS
                                                           else ambient_c * 9 / 5 + 32, 2),
            "ground_z_m": round(report.ground_z_m, 3),
            "csv_path": str(csv_sink.path), "csv_object": f"{flight_id}.csv.gz",
            "rows_written": None, "csv_uploaded": False,
        })
        if self.history is not None:
            self.history.flight_started(flight_id, str(mode), program)
        self._set(flight={"id": flight_id, "phase": "starting", "detail": ""})
        return flight_id

    def _finish_flight(self, *, status: str, outcome: str | None = None,
                       error: str | None = None, abort_reason: str | None = None) -> None:
        flight_id, recorder = self._flight_id, self._recorder
        self._flight_id, self._recorder = None, None
        if flight_id is None:
            return
        rows = 0
        if recorder is not None:
            recorder.stop()
            rows = recorder.rows_written
        if self.history is not None:
            self.history.flight_finished(flight_id, outcome=outcome or status,
                                         abort_reason=abort_reason)
        self._outbox.update(Kind.FLIGHT, flight_id, lambda p: p.update({
            "ended_at": datetime.now(UTC).isoformat(), "status": status,
            "outcome": outcome, "error": error, "abort_reason": abort_reason,
            "rows_written": rows,
        }))
        if self._syncer is not None:
            self._syncer.trigger()

    # ── helpers ──────────────────────────────────────────────────────────

    def _require_ready(self, what: str) -> None:
        self._require_operator()
        with self._lock:
            state = self._snapshot.state
        if state is State.BUSY:
            raise SessionError("Something is already running. Wait for it to finish.")
        if state is not State.READY:
            raise SessionError(f"Run the checks and confirm the area before starting {what}.")
        if self._snapshot.retry_required:
            raise SessionError(
                "The last flight ended abnormally. Press Retry to check the drone again "
                f"before starting {what}."
            )

    def _require_link(self) -> DroneLink:
        if self.link is None or not self.link.is_open:
            raise SessionError("Not connected to the drone.")
        return self.link

    def _require_report(self) -> ReadyReport:
        if self.report is None:
            raise SessionError("Run the checks first.")
        return self.report

    def _close_link(self) -> None:
        with self._link_lock:
            if self._unsubscribe_telemetry is not None:
                try:
                    self._unsubscribe_telemetry()
                except Exception:
                    log.debug("telemetry unsubscribe failed")
                self._unsubscribe_telemetry = None
            if self.link is not None:
                try:
                    self.link.close()
                except Exception:
                    log.exception("closing the link failed")
                self.link = None
                self._link_ready_for = None
                if self._on_link_down is not None:
                    try:
                        self._on_link_down()
                    except Exception:
                        log.exception("link-down hook failed")
        # Whatever closed it, the radio is free: look for the drone again soon
        # (the standby loop decides whether it may — not during a session).
        self._wake_standby(STANDBY_SOON_S)
