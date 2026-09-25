"""The agent's local HTTP and WebSocket API.

This is what the desktop app talks to. It binds to **localhost by default**: it
can arm a real drone, so exposing it on a network is an explicit, deliberate
act — and even on localhost every command needs the local control token, since
any page the operator has open can reach 127.0.0.1.

Two surfaces, split by how much delay each tolerates:

  REST       commands. One request, delay is harmless.
  WebSocket  the live stream out (telemetry, session state, checks) and the
             manual-control intent in. Needs 10 Hz and cannot cross the
             internet.

What is deliberately **not** here any more: `POST /flight/mission` and
`/preflight` used to fly a drone with no authentication of any kind, and they
bypassed the checks. Flying now goes through a session, which needs the token,
a signed-in operator, passing checks and a confirmed area.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cropwatcher import history
from cropwatcher.api.events import EventHub
from cropwatcher.api.tokens import HEADER, load_or_create_token
from cropwatcher.camera import DeckStream, FrameSource, NoCamera, TestPattern
from cropwatcher.camera.deck import parse_addr
from cropwatcher.camera.recording import Recorder
from cropwatcher.camera.wifi import DeckWifi, Phase, WifiError
from cropwatcher.drone_setup import DroneSetup, SetupError
from cropwatcher.paths import data_dir
from cropwatcher.session import Mode, Session, SessionError, State
from cropwatcher.sync.cloud import SupabaseCloud
from cropwatcher.sync.outbox import Outbox
from cropwatcher.sync.syncer import Syncer

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
#: How long a REMEMBERED deck address may go unanswered before the window is
#: told it is stale and the drone needs a restart (wifi.WifiState.remembered).
STALE_ADDRESS_S = 15.0
#: At most one automatic deck restart per this many seconds: a deck out of
#: range will not come back by being restarted in a loop.
REJOIN_EVERY_S = 60.0
DEFAULT_PORT = 8765

# The desktop window itself. WebKit serves it from `tauri://localhost` on macOS
# and `http://tauri.localhost` on Windows; `localhost:1420` is `pnpm tauri dev`.
# These may send commands — and still need the control token to be obeyed.
DESKTOP_ORIGINS = (
    "tauri://localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
)

# Websites allowed to *read* status, so the dashboard can say whether the agent
# is running. They may never command: a page on the internet cannot know the
# token, and these origins are not allowed to POST at all.
WEBSITE_ORIGINS = (
    "https://drone-capstone.vercel.app",
    "http://localhost:3000",
)

BUILTIN_ORIGINS = (*DESKTOP_ORIGINS, *WEBSITE_ORIGINS)


def allowed_origins() -> frozenset[str]:
    extra = os.environ.get("CROPWATCHER_ALLOWED_ORIGINS", "")
    return frozenset(
        [*BUILTIN_ORIGINS, *(o.strip().rstrip("/") for o in extra.split(",") if o.strip())]
    )


# ── request models ───────────────────────────────────────────────────────


class SignInRequest(BaseModel):
    email: str
    password: str


class ModeRequest(BaseModel):
    mode: Mode


class ProgramRequest(BaseModel):
    height_m: float = Field(0.30, gt=0, le=1.0, description="metres above the floor")
    hold_s: float = Field(10.0, gt=0, le=60.0)
    ambient: str = Field("22C", description="room temperature, e.g. 74F or 22C")


class ManualRequest(BaseModel):
    ambient: str = "22C"


class HoldRequest(BaseModel):
    # The ceiling is the controller's, and it depends on whether the drone can
    # see the base stations (1.00 m assisted, 0.80 m on the barometer), so the
    # real check is there. This bound only keeps an absurd number out of the
    # flight code.
    height_m: float = Field(0.30, gt=0, le=1.0, description="metres above the floor")


class DeckWifiRequest(BaseModel):
    ssid: str = Field(..., min_length=1, max_length=64)
    #: Empty for an open network. Never logged and never returned.
    password: str = Field("", max_length=128)


class ConfirmRequest(BaseModel):
    #: The operator accepts flying with no base stations: height from the
    #: barometer only, no position hold, no drift or fence guard. Required only
    #: when the checks reported that assistance is unavailable.
    accept_unassisted: bool = False


# ── app state ────────────────────────────────────────────────────────────


class Agent:
    """Everything the API drives. Built once, at startup."""

    def __init__(self) -> None:
        self.hub = EventHub()
        self.outbox = Outbox()
        self.token = load_or_create_token()
        self.cloud = SupabaseCloud(
            os.environ.get("SUPABASE_URL", "").strip(),
            os.environ.get("SUPABASE_ANON_KEY", "").strip(),
        )
        self.syncer = Syncer(
            self.outbox,
            lambda: self.cloud if self.cloud.operator is not None else None,
            on_status=lambda status: self.hub.publish("sync", status.to_dict()),
        )
        self.camera: FrameSource = _camera_from_env()
        #: The Wi-Fi network the AI deck should join, given by the desktop at
        #: sign-in and sent to the drone on every link. When the deck reports
        #: its address, the camera follows it there.
        self.deck_wifi = DeckWifi(
            on_change=lambda state: self.hub.publish("camera_wifi", state.to_dict()),
            on_ip=self._deck_joined,
            joined_file=data_dir() / "deck-wifi.json",
        )
        #: Every camera frame of a session, to disk first (camera/recording.py).
        #: Standby frames are shown, never recorded.
        self.recorder = Recorder(self.outbox, position=lambda: self.session.position())
        if isinstance(self.camera, DeckStream):
            self.camera.add_listener(self.recorder.on_frame)
        self.session = Session(
            cloud=self.cloud, outbox=self.outbox, syncer=self.syncer,
            publish=self.hub.publish, on_link_ready=self._link_ready,
            on_link_down=self._link_down,
            on_session_open=self.recorder.start, on_session_close=self.recorder.stop,
        )
        #: The Set up page: installs the camera software on a drone.
        self.setup = DroneSetup(
            pause_radio=self._hold_radio, resume_radio=self._release_radio,
            publish=lambda state: self.hub.publish("setup", state),
        )

    #: Stops following the deck's console, once the link it came from closes.
    _unwatch: Callable[[], None] | None = None
    #: The Crazyflie of the link that is up; None when down.
    _cf: Any = None
    _last_rejoin: float = 0.0

    def _link_ready(self, cf: Any) -> None:
        """A link is up (standby's or a session's): follow the deck's Wi-Fi
        reports for as long as it lasts, then hand it the network."""
        self._cf = cf
        self._unwatch = self.deck_wifi.watch(cf)
        self.deck_wifi.apply(cf)

    def rejoin(self, *, reason: str) -> bool:
        """Make the deck join afresh and ANNOUNCE ITS ADDRESS — by restarting
        the drone over the radio (Session.restart_drone), between sessions only.

        The deck's address is the network's to give, not ours to fix: on a
        campus network it changed under us without the drone restarting
        (2026-09-24), a static address is not ours to take there, and the deck
        firmware has no name lookup (mDNS was never finished — Bitcraze). The
        one reliable source is the drone saying it over the radio; this makes it
        say it again. False when a session runs, or no one is signed in.
        """
        try:
            self.session.restart_drone(reason=reason)
        except SessionError as e:
            log.info("not restarting the drone (%s): %s", reason, e)
            return False
        self._last_rejoin = time.monotonic()
        return True

    def watchdog(self) -> None:
        """Every few seconds: is the camera stuck on an address that no longer
        answers? Then have the deck say its current one. Never in a loop."""
        while True:
            time.sleep(5.0)
            try:
                wifi = self.deck_wifi.state()
                camera = self.camera
                if (self._cf is None or not isinstance(camera, DeckStream)
                        or time.monotonic() - self._last_rejoin < REJOIN_EVERY_S):
                    continue
                # No frames for a while, whatever the cause: the address went
                # stale (connects fail), OR the deck accepts and sends nothing
                # (its ESP32 disconnect bug — firmware/aideck-esp). A restart
                # clears both.
                stuck = (wifi.phase is Phase.JOINED and not camera.status().live
                         and camera.no_frames_for() > STALE_ADDRESS_S)
                if stuck:
                    why = ("no answer" if camera.unreachable_for() > 0 else "no frames")
                    self.rejoin(reason=f"{why} at {wifi.ip} for "
                                       f"{camera.no_frames_for():.0f} s")
                elif wifi.phase is Phase.FAILED and wifi.needs_restart:
                    self.rejoin(reason="joined earlier with an unknown address")
            except Exception:
                log.exception("camera watchdog failed; it keeps running")

    def _link_down(self) -> None:
        self._cf = None
        unwatch, self._unwatch = self._unwatch, None
        if unwatch is not None:
            unwatch()
        self.deck_wifi.link_down()

    def _hold_radio(self) -> None:
        """Set up flashes over the radio: standby lets go of it first."""
        with contextlib.suppress(SessionError):
            self.session.disconnect_drone()

    def _release_radio(self) -> None:
        with contextlib.suppress(SessionError):
            self.session.connect_drone()

    def _deck_joined(self, ip: str) -> None:
        if isinstance(self.camera, DeckStream):
            self.camera.set_host(ip)
            self.camera.kick()


def _camera_from_env() -> FrameSource:
    """Where camera frames come from, chosen by CROPWATCHER_CAMERA.

    unset   NoCamera — the default, because joining the deck's access point
            takes this laptop off its normal network, so it is opt-in.
    deck    the AI deck's Wi-Fi streamer, at CROPWATCHER_DECK_ADDR
            (default 192.168.4.1:5000). The laptop must be on the deck's Wi-Fi.
    test    a generated pattern, which proves the route, the content policy
            and the window without a camera.
    """
    choice = os.environ.get("CROPWATCHER_CAMERA", "").strip().lower()
    if choice == "deck":
        return DeckStream(parse_addr(os.environ.get("CROPWATCHER_DECK_ADDR")))
    if choice == "test":
        return TestPattern()
    return NoCamera()


agent = Agent()


def _restore_sign_in() -> None:
    try:
        agent.session.restore_sign_in()
    except Exception:
        log.exception("restoring the saved sign-in failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    agent.hub.bind(asyncio.get_running_loop())
    agent.syncer.start()
    # Signing back in is a network call; the API must answer /health while it
    # happens, so it runs beside startup rather than in front of it.
    threading.Thread(target=_restore_sign_in, daemon=True, name="restore-sign-in").start()
    # Hold the drone on standby whenever someone is signed in and no session
    # runs: vitals and the camera before any session. CROPWATCHER_STANDBY=0
    # turns it off — for tests, and for a developer who wants the radio free.
    if os.environ.get("CROPWATCHER_STANDBY", "1").strip() != "0":
        agent.session.start_standby()
        threading.Thread(target=agent.watchdog, name="camera-watchdog", daemon=True).start()
    log.info("agent API on %s:%d", DEFAULT_HOST, DEFAULT_PORT)
    yield
    agent.session.stop_standby()
    try:
        agent.session.end("agent shutting down")
    except Exception:
        log.exception("could not end the session cleanly")
    agent.syncer.stop()


app = FastAPI(title="CropWatcher Agent", version="0.2.0", lifespan=lifespan)


#: Refusals already logged, as (origin, reason). A browser refused a preflight
#: shows its page only "could not reach the agent" — the same words as an agent
#: that is not running — so the agent's log is the one place the difference is
#: written down. Once per origin and reason: a page retrying in a loop must not
#: bury the log, and the cap bounds what a page inventing origins can add.
_cors_refusals_logged: set[tuple[str, str]] = set()
CORS_REFUSALS_LOGGED_MAX = 50


def _log_cors_refusal(origin: str, reason: str, method: str, path: str) -> None:
    key = (origin, reason)
    if key in _cors_refusals_logged or len(_cors_refusals_logged) >= CORS_REFUSALS_LOGGED_MAX:
        return
    _cors_refusals_logged.add(key)
    log.warning("refused a cross-origin %s %s from origin %r: %s (logged once per origin)",
                method, path, origin or "(none)", reason)


class LocalCORS(BaseHTTPMiddleware):
    """CORS, with the method list decided per origin.

    The desktop window is a browser too: WebKit enforces CORS on its `fetch`,
    so a single allow-list of GET blocked the app's own commands — every button
    failed with "could not reach the agent" while the WebSocket, which CORS does
    not cover, worked fine. That is what this asymmetry is for:

      desktop origins   GET and POST — plus the control token, always
      website origins   GET only, so the dashboard can see if the agent runs
      anything else     no CORS headers at all

    Removing the method split would let any page the operator has open POST to
    the agent. It would still be refused for want of the token, but a drone is
    not the place to rely on one gate.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        desktop = origin in DESKTOP_ORIGINS
        known = desktop or origin in allowed_origins()
        methods = "GET, POST, OPTIONS" if desktop else "GET, OPTIONS"

        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            requested = request.headers["access-control-request-method"].upper()
            if not known:
                _log_cors_refusal(origin, "origin not allowed", requested, request.url.path)
                return Response(status_code=400, content="Disallowed CORS origin")
            if requested not in methods:
                _log_cors_refusal(origin, "method not allowed", requested, request.url.path)
                return Response(status_code=400, content="Disallowed CORS method")
            return Response(status_code=200, headers=self._headers(origin, methods, preflight=True))

        response = await call_next(request)
        if known:
            response.headers.update(self._headers(origin, methods, preflight=False))
        return response

    @staticmethod
    def _headers(origin: str, methods: str, *, preflight: bool) -> dict[str, str]:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": methods,
            "Vary": "Origin",
        }
        if preflight:
            headers["Access-Control-Allow-Headers"] = f"content-type, {HEADER.lower()}"
            headers["Access-Control-Max-Age"] = "600"
            # Chrome's Private Network Access preflight: a public https page
            # fetching 127.0.0.1 needs this answered or it discards the reply,
            # and the /setup banner can only ever say "not running".
            headers["Access-Control-Allow-Private-Network"] = "true"
        return headers


app.add_middleware(LocalCORS)


def require_token(x_agent_token: str = Header(default="")) -> None:
    """Every command. Rejects anything that is not the app that launched us."""
    if not x_agent_token or x_agent_token != agent.token:
        raise HTTPException(
            status_code=401, detail="This client is not authorised to fly the drone."
        )


Command = Depends(require_token)


def _run(action) -> dict:
    """Turn a refusal into a 409 the app can show verbatim."""
    try:
        action()
    except SessionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return agent.session.snapshot().to_dict()


# ── read-only ────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    """Liveness. No radio, no token: the setup page polls this to decide
    whether to show Download or Start."""
    return {"ok": True, "service": "cropwatcher-agent", "version": "0.2.0"}


@app.get("/status")
def status() -> dict:
    """A summary safe to show without the token — no operator details."""
    snapshot = agent.session.snapshot()
    return {
        "state": str(snapshot.state),
        "mode": str(snapshot.mode),
        "signed_in": snapshot.operator is not None,
        "drone_connected": snapshot.drone is not None,
        "sync": agent.syncer.status.to_dict(),
    }


@app.get("/camera")
def camera_status() -> dict:
    """What the Camera tab shows when there is nothing to show.

    Unauthenticated, like /status and for the same reason: it carries no
    operator details and commands nothing. `deck_fitted` is the DRONE's own
    answer (deck.bcAI, read over the radio during the checks), so the tab
    reports what was asked rather than what someone typed.
    """
    status = agent.camera.status()
    snapshot = agent.session.snapshot()
    payload = {**status.to_dict(), "deck_fitted": snapshot.ai_deck}
    # No frames AND no radio link: the likeliest reason is the drone itself —
    # off, or its battery flat — not the network. Say that first, rather than
    # a network theory about an address the drone may no longer have.
    radio_up = snapshot.radio.get("state") == "connected"
    wifi = agent.deck_wifi.state()
    #: The agent is actively working towards a picture — the window shows a
    #: spinner and the reason, not "no signal".
    payload["connecting"] = False
    if not status.live and isinstance(agent.camera, DeckStream):
        if snapshot.radio.get("state") == "restarting":
            payload["connecting"] = True
            payload["reason"] = ("Restarting the drone so its camera rejoins and reports "
                                 "its address — about 15 s.")
        elif not radio_up:
            payload["reason"] = (
                "The drone is not connected — it may be switched off or its battery "
                "flat. Its camera streams once the drone is on and connected."
            )
        elif wifi.phase in (Phase.SENDING, Phase.JOINING, Phase.RECONNECTING):
            payload["connecting"] = True
            payload["reason"] = wifi.message
        elif wifi.phase is Phase.JOINED and \
                agent.camera.no_frames_for() > STALE_ADDRESS_S:
            # Not at that address any more. The watchdog restarts the deck so it
            # says its new one; the window says what is happening meanwhile.
            payload["connecting"] = True
            unreachable = agent.camera.unreachable_for() > 0
            what = (f"The drone is no longer at {wifi.ip}." if unreachable else
                    "The drone's camera accepts the connection but sends nothing.")
            payload["reason"] = (
                f"{what} Restarting the drone so it starts clean — about 15 s."
                if snapshot.state is State.IDLE else
                f"{what} End the session to let the drone restart."
            )
        elif wifi.phase is Phase.JOINED:
            payload["connecting"] = True
    return payload


@app.get("/camera/recording", dependencies=[Command])
def camera_recording() -> dict:
    """The session's recording, if one is running: how many frames, the latest."""
    recording = agent.recorder.current
    return recording.summary() if recording is not None else {"recording": False}


@app.get("/camera/recording/frames", dependencies=[Command])
def camera_recording_frames(
    after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000),
) -> dict:
    """Recorded frames after `after`, for the backlog strip."""
    recording = agent.recorder.current
    frames = recording.after(after, limit) if recording is not None else []
    return {"frames": [f.to_dict() for f in frames]}


@app.get("/camera/recording/frame/{which}", dependencies=[Command])
def camera_recording_frame(which: str) -> Response:
    """One recorded frame — a number, or "latest" — read back FROM DISK, so
    what the window shows is what was saved. 204 when there is none."""
    recording = agent.recorder.current
    if recording is None:
        return Response(status_code=204)
    if which == "latest":
        frame = recording.latest()
    else:
        try:
            frame = recording.get(int(which))
        except ValueError:
            raise HTTPException(status_code=404, detail="No such frame.") from None
    if frame is None:
        return Response(status_code=204)
    try:
        data = recording.path(frame).read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="That frame is gone from disk.") from None
    return Response(content=data, media_type=frame.content_type,
                    headers={"Cache-Control": "no-store"})


@app.get("/camera/wifi", dependencies=[Command])
def camera_wifi() -> dict:
    """The network the deck is set to join, and how far it got. No password."""
    return agent.deck_wifi.state().to_dict()


@app.put("/camera/wifi", dependencies=[Command])
def set_camera_wifi(body: DeckWifiRequest) -> dict:
    """Set the network the deck joins. Applied on the next drone link — or now,
    when a session already holds one."""
    try:
        state = agent.deck_wifi.configure(body.ssid, body.password)
    except WifiError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # A link already open — a session's, or standby's — gets it now; otherwise
    # the next link does.
    # A connected drone is handed it now. If it already joined a network this
    # power-on it answers ALREADY_APPLIED, the state says needs_restart, and the
    # watchdog restarts it between sessions — no restart when none is needed.
    cf = agent._cf
    if cf is not None and agent.session.snapshot().ai_deck:
        threading.Thread(target=agent.deck_wifi.apply, args=(cf,),
                         name="deck-wifi", daemon=True).start()
    return state.to_dict()


@app.post("/camera/wifi/rejoin", dependencies=[Command])
def rejoin_camera_wifi() -> dict:
    """Restart the drone over the radio so its camera rejoins and announces its
    address — the operator's "Reconnect camera". Between sessions only."""
    if not agent.rejoin(reason="the operator asked"):
        raise HTTPException(status_code=409, detail="End the session first — the drone "
                                                    "is only restarted between sessions.")
    return agent.deck_wifi.state().to_dict()


@app.delete("/camera/wifi", dependencies=[Command])
def forget_camera_wifi() -> dict:
    return agent.deck_wifi.forget().to_dict()


@app.get("/camera/frame")
def camera_frame() -> Response:
    """The latest frame, as an image.

    Unauthenticated ON PURPOSE, and it is the narrowest route here: it is
    read-only, it commands nothing, and the agent binds localhost. An <img> tag
    cannot send a header, so requiring the token would mean putting it in a
    query string — which the WebSocket deliberately avoids because a query
    string lands in access logs. /status is already open and carries more.

    204 when there is no camera: an empty body the window can distinguish from
    a broken route, which a 404 would not.
    """
    frame = agent.camera.frame()
    if frame is None:
        return Response(status_code=204)
    return Response(
        content=frame,
        media_type=agent.camera.content_type,
        # A live feed must never be served from cache.
        headers={"Cache-Control": "no-store"},
    )


@app.get("/session", dependencies=[Command])
def session_state() -> dict:
    return agent.session.snapshot().to_dict()


# ── auth ─────────────────────────────────────────────────────────────────


@app.post("/auth/sign-in", dependencies=[Command])
def sign_in(request: SignInRequest) -> dict:
    return _run(lambda: agent.session.sign_in(request.email, request.password))


@app.post("/auth/sign-out", dependencies=[Command])
def sign_out() -> dict:
    return _run(agent.session.sign_out)


# ── history ──────────────────────────────────────────────────────────────
#
# The operator's own sessions, read from this laptop. Token-gated like every
# command: it names people and carries their flight data.


@app.get("/history/sessions", dependencies=[Command])
def list_sessions(
    limit: int = Query(20, ge=1, le=200),
    mode: Mode | None = None,           # only sessions that used this mode
) -> list[dict]:
    return history.list_sessions(limit, mode=str(mode) if mode else None)


@app.get("/history/sessions/{session_id}", dependencies=[Command])
def read_session(session_id: str) -> dict:
    try:
        found = history.read_session(session_id)
    except ValueError:
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail="No such session on this computer.")
    return found


@app.get("/history/sessions/{session_id}/samples", dependencies=[Command])
def read_samples(
    session_id: str,
    variables: str = Query(..., alias="vars", description="comma-separated variable names"),
    limit: int = Query(history.MAX_SAMPLES_RETURNED, ge=1, le=history.MAX_SAMPLES_RETURNED),
    mode: Mode | None = None,           # only readings taken in this mode
) -> list[dict]:
    names = [v.strip() for v in variables.split(",") if v.strip()]
    try:
        return history.read_samples(
            session_id, names, mode=str(mode) if mode else None, limit=limit)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such session on this computer.") from None


# ── session ──────────────────────────────────────────────────────────────


@app.post("/session/mode", dependencies=[Command])
def set_mode(request: ModeRequest) -> dict:
    return _run(lambda: agent.session.set_mode(request.mode))


@app.post("/session/start", dependencies=[Command])
def start_session() -> dict:
    return _run(agent.session.start)


@app.post("/session/confirm", dependencies=[Command])
def confirm_area(request: ConfirmRequest | None = None) -> dict:
    accept = bool(request and request.accept_unassisted)
    return _run(lambda: agent.session.confirm_area(accept_unassisted=accept))


@app.post("/session/health-test", dependencies=[Command])
def health_test() -> dict:
    return _run(agent.session.health_test)


# The propeller-only test's old path, now the full battery & motor test.
app.post("/session/prop-test", dependencies=[Command])(health_test)


@app.post("/session/retry", dependencies=[Command])
def retry() -> dict:
    return _run(agent.session.retry)


@app.post("/session/program", dependencies=[Command])
def run_program(request: ProgramRequest) -> dict:
    return _run(lambda: agent.session.run_program(
        height_m=request.height_m, hold_s=request.hold_s, ambient=request.ambient))


@app.post("/session/manual/arm", dependencies=[Command])
def arm_manual(request: ManualRequest) -> dict:
    return _run(lambda: agent.session.arm_manual(ambient=request.ambient))


@app.post("/session/manual/hold", dependencies=[Command])
def hold_manual(request: HoldRequest) -> dict:
    """Rise to a height and hold it, without the operator holding W."""
    return _run(lambda: agent.session.hold_manual(height_m=request.height_m))


@app.post("/session/land", dependencies=[Command])
def land() -> dict:
    return _run(agent.session.land)


@app.post("/session/emergency-stop", dependencies=[Command])
def emergency_stop() -> dict:
    """Always answers. A stop that can fail is not a stop."""
    return _run(agent.session.emergency_stop)


@app.post("/session/end", dependencies=[Command])
def end_session() -> dict:
    return _run(lambda: agent.session.end("operator"))


@app.post("/drone/connect", dependencies=[Command])
def drone_connect() -> dict:
    """Look for the drone now and hold it on standby — vitals and camera with
    no session. Never arms."""
    try:
        agent.session.connect_drone()
    except SessionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return agent.session.snapshot().to_dict()


@app.post("/drone/disconnect", dependencies=[Command])
def drone_disconnect() -> dict:
    """Release the radio until Connect, so another tool can use it."""
    try:
        agent.session.disconnect_drone()
    except SessionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return agent.session.snapshot().to_dict()


@app.get("/setup", dependencies=[Command])
def setup_state() -> dict:
    """Where Set up is: what the drone has, what is installing, how far."""
    return agent.setup.state()


def _setup_allowed() -> None:
    if agent.session.snapshot().state is not State.IDLE:
        raise HTTPException(status_code=409, detail="End the session first — Set up "
                                                    "needs the radio to itself.")


@app.post("/setup/check", dependencies=[Command])
def setup_check() -> dict:
    """Read what the drone has installed. Changes nothing on the drone."""
    _setup_allowed()
    try:
        agent.setup.check()
    except SetupError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return agent.setup.state()


@app.post("/setup/install", dependencies=[Command])
def setup_install() -> dict:
    """Install whatever is missing, in order, then guide the battery unplug."""
    _setup_allowed()
    try:
        agent.setup.install()
    except SetupError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return agent.setup.state()


@app.post("/sync/now", dependencies=[Command])
def sync_now() -> dict:
    agent.syncer.trigger()
    return agent.syncer.status.to_dict()


# ── the live socket ──────────────────────────────────────────────────────


@app.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    """Session state, checks and telemetry out; manual intent and heartbeat in.

    The token arrives in the first message rather than the URL: a query string
    is written to the access log, and this one grants control of a drone.
    """
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in allowed_origins():
        log.warning("refused a live socket from origin %r", origin)
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        opening = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
    except (TimeoutError, Exception):
        await websocket.close(code=1008)
        return

    if opening.get("type") != "auth" or opening.get("token") != agent.token:
        await websocket.send_json({"type": "error", "message": "not authorised"})
        await websocket.close(code=1008)
        return

    queue = agent.hub.subscribe()
    await websocket.send_json({"type": "session", **agent.session.snapshot().to_dict()})
    await websocket.send_json({"type": "sync", **agent.syncer.status.to_dict()})

    async def pump() -> None:
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "intent":
                agent.session.set_intent(message.get("keys", {}))
            elif kind == "heartbeat":
                agent.session.heartbeat()
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        # Expected: the window closed. The manual controller's heartbeat
        # timeout lands the drone by itself.
        log.info("live socket disconnected")
    except Exception:
        log.exception("live socket failed")
    finally:
        pump_task.cancel()
        agent.hub.unsubscribe(queue)


# ── serving ──────────────────────────────────────────────────────────────


class QuietHealthFilter(logging.Filter):
    """Log the first few /health polls, then stop.

    The app polls /health every 2 s; without this the agent log is nothing but
    those lines, and the flight messages that matter scroll away.
    """

    def __init__(self, keep: int = 10) -> None:
        super().__init__()
        self._keep = keep
        self._seen = 0

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "/health" not in message:
            return True
        self._seen += 1
        if self._seen == self._keep:
            log.info("further /health polls will not be logged")
        return self._seen <= self._keep


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          exit_with_parent: bool = False) -> None:
    """Run the API. Binding beyond localhost is deliberate — see module docs."""
    import uvicorn

    if host not in {"127.0.0.1", "localhost"}:
        log.warning(
            "binding to %s — this API can arm a drone. Only do this on a trusted network.", host
        )
    if exit_with_parent:
        exit_when_parent_closes()

    logging.getLogger("uvicorn.access").addFilter(QuietHealthFilter())
    uvicorn.run(app, host=host, port=port, log_level="info")


def exit_when_parent_closes() -> None:
    """Shut down when whoever launched us goes away. Used by the desktop app.

    Killing the sidecar from the desktop side is not enough, and the reason is
    worth writing down because it is invisible and it strands an armed drone.

    A PyInstaller one-file binary is **two** processes: a bootloader that
    unpacks the archive, and the real Python process it then spawns. Measured
    from the built app:

        desktop(43661) → bootloader(43666) → python(43670)   ← holds the radio

    Tauri knows only about the bootloader. Killing it leaves the Python process
    orphaned onto `launchd`, still holding the radio and the port. The next
    launch then reports "no drone found" with a drone plainly sitting there.

    Stdin is the fix because it is the one handle the real process inherits:
    when the parent dies its pipe closes, and the read below returns EOF in the
    process that actually matters. The session is ended first — this path can
    run while the drone is in the air.
    """
    import sys
    import threading

    def watch() -> None:
        try:
            while sys.stdin.readline():
                pass
        except Exception:  # noqa: BLE001 - a closed pipe must not raise here
            pass

        log.warning("parent process closed — landing and shutting down")
        try:
            agent.session.end("the app closed")
        except Exception:
            log.exception("could not end the session; stopping the motors")
        os._exit(0)

    threading.Thread(target=watch, daemon=True, name="parent-watchdog").start()


__all__ = ["app", "serve", "agent", "exit_when_parent_closes"]
