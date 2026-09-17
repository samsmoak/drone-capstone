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
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cropwatcher import history
from cropwatcher.api.events import EventHub
from cropwatcher.api.tokens import HEADER, load_or_create_token
from cropwatcher.session import Mode, Session, SessionError
from cropwatcher.sync.cloud import SupabaseCloud
from cropwatcher.sync.outbox import Outbox
from cropwatcher.sync.syncer import Syncer

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
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
        self.session = Session(
            cloud=self.cloud, outbox=self.outbox, syncer=self.syncer,
            publish=self.hub.publish,
        )


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
    log.info("agent API on %s:%d", DEFAULT_HOST, DEFAULT_PORT)
    yield
    try:
        agent.session.end("agent shutting down")
    except Exception:
        log.exception("could not end the session cleanly")
    agent.syncer.stop()


app = FastAPI(title="CropWatcher Agent", version="0.2.0", lifespan=lifespan)


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
            if not known:
                return Response(status_code=400, content="Disallowed CORS origin")
            requested = request.headers["access-control-request-method"].upper()
            if requested not in methods:
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


@app.post("/session/prop-test", dependencies=[Command])
def prop_test() -> dict:
    return _run(agent.session.prop_test)


@app.post("/session/program", dependencies=[Command])
def run_program(request: ProgramRequest) -> dict:
    return _run(lambda: agent.session.run_program(
        height_m=request.height_m, hold_s=request.hold_s, ambient=request.ambient))


@app.post("/session/manual/arm", dependencies=[Command])
def arm_manual(request: ManualRequest) -> dict:
    return _run(lambda: agent.session.arm_manual(ambient=request.ambient))


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
