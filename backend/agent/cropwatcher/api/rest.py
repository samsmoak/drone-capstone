"""The agent's local HTTP and WebSocket API.

This is what the desktop app and the browser talk to. It binds to **localhost
by default**: it can arm a real drone and has no authentication of its own, so
exposing it on a network is an explicit, deliberate act.

Two surfaces, split by how much delay each tolerates:

  REST       mission control. One request, delay is harmless.
  WebSocket  manual control. Needs 50 Hz and cannot cross the internet.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from cropwatcher.api.manual import Intent, ManualController
from cropwatcher.flight import core, missions
from cropwatcher.flight.missions import Mission, MissionValidationError
from cropwatcher.flight.preflight import PreflightError
from cropwatcher.safety.geofence import Geofence

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Browser origins allowed to talk to this agent.
#
# Binding to localhost does NOT keep websites out. Any page the operator has
# open can send requests to 127.0.0.1, and WebSockets are not covered by CORS
# at all — without an Origin check, a page on any site could open /ws/manual
# and fly the drone. So the socket checks this list itself, and CORS uses the
# same list for the read-only endpoints the dashboard polls.
#
# Extend with CROPWATCHER_ALLOWED_ORIGINS (comma-separated) for a preview
# deployment; never with "*".
BUILTIN_ORIGINS = (
    "https://drone-capstone.vercel.app",
    "http://localhost:3000",       # next dev
    "tauri://localhost",           # desktop app, macOS
    "http://tauri.localhost",      # desktop app, Windows
    "http://localhost:1420",       # desktop app, tauri dev
)


def allowed_origins() -> frozenset[str]:
    extra = os.environ.get("CROPWATCHER_ALLOWED_ORIGINS", "")
    return frozenset(
        [*BUILTIN_ORIGINS, *(o.strip().rstrip("/") for o in extra.split(",") if o.strip())]
    )


def origin_permitted(origin: str | None) -> bool:
    """Whether a request's Origin may use this agent.

    A missing Origin is permitted: browsers always send one on a WebSocket
    handshake, so its absence means a non-browser client — the CLI, a test, a
    script on this machine — which already has local access anyway.
    """
    return origin is None or origin in allowed_origins()


# ── request models ───────────────────────────────────────────────────────


class HoverRequest(BaseModel):
    height_m: float = Field(0.5, gt=0, le=3.0, description="metres above ground")
    secs: float = Field(5.0, gt=0, le=300.0)
    ambient: str = Field("22C", description="e.g. 74F or 22C")
    force: bool = False


class MissionRequest(BaseModel):
    plan: dict[str, Any]
    fence_m: float = Field(2.0, gt=0, le=10.0)
    ambient: str = "22C"
    dry_run: bool = False
    force: bool = False


# ── app state ────────────────────────────────────────────────────────────


class AgentState:
    """Whatever is currently happening. One drone, so one flight at a time."""

    def __init__(self) -> None:
        self.uri = core.DEFAULT_URI
        self.busy = False
        self.current: str | None = None
        self.manual: ManualController | None = None

    def claim(self, what: str) -> None:
        if self.busy:
            raise HTTPException(
                status_code=409,
                detail=f"the drone is already busy with: {self.current}",
            )
        self.busy = True
        self.current = what

    def release(self) -> None:
        self.busy = False
        self.current = None


state = AgentState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("agent API starting on %s:%d", DEFAULT_HOST, DEFAULT_PORT)
    yield
    if state.manual is not None:
        state.manual.stop()


app = FastAPI(title="CropWatcher Agent", version="0.1.0", lifespan=lifespan)

# GET only. The dashboard needs to see whether the agent is running; it never
# needs to start a flight from a browser tab, and a POST that arms a drone
# should not be reachable from a web page at all.
#
# `allow_private_network` answers Chrome's Private Network Access preflight,
# without which a public https page cannot reach 127.0.0.1 regardless of CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins()),
    allow_methods=["GET"],
    allow_private_network=True,
)


# ── read-only ────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    """Liveness. The web app uses this to decide whether to show Download
    or Start, so it must answer even when no drone is connected."""
    return {"ok": True, "service": "cropwatcher-agent", "version": "0.1.0"}


@app.get("/status")
def status() -> dict:
    found = core.scan()
    return {
        "drone_connected": bool(found),
        "uri": found[0] if found else None,
        "busy": state.busy,
        "current": state.current,
        "manual_state": str(state.manual.state) if state.manual else None,
    }


@app.get("/preflight")
def preflight_check() -> dict:
    """Run every gate without spinning a motor."""
    from cropwatcher.flight import preflight

    try:
        with core.connect(state.uri) as scf:
            report = preflight.run(scf, hold_seconds=0.0)
    except PreflightError as e:
        # A refusal is a real answer, not a server error. 409 so the UI can
        # show the reason rather than a generic failure.
        raise HTTPException(status_code=409, detail={
            "reason": e.reason, "detail": e.detail,
        }) from e
    except core.FlightError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "battery_v": round(report.vbat, 2),
        "can_fly": report.can_fly,
        "base_stations": report.base_stations,
        "ground_z_m": round(report.ground_z_m, 3),
        "estimate_spread_m": round(report.estimate_spread_m, 4),
        "endurance_s": round(report.endurance_s),
    }


# ── flying ───────────────────────────────────────────────────────────────


@app.post("/flight/mission")
def run_mission(request: MissionRequest) -> dict:
    """Validate a plan and fly it. `dry_run` validates without connecting."""
    try:
        mission = Mission.from_dict(request.plan)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"malformed plan: {e}") from e

    geofence = Geofence.square(request.fence_m)
    try:
        mission.validate(geofence=geofence)
    except MissionValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if request.dry_run:
        return {
            "validated": True,
            "flown": False,
            "waypoints": len(mission.waypoints),
            "estimated_s": round(mission.estimated_duration_s()),
            "plan": mission.describe(),
        }

    state.claim(f"mission: {mission.name}")
    events: list[dict] = []
    try:
        with core.session(
            state.uri,
            hold_seconds=mission.estimated_duration_s(),
            force=request.force,
        ) as flight:
            for event in missions.execute(mission, flight):
                events.append({"kind": str(event.kind), "detail": event.detail})
    except PreflightError as e:
        raise HTTPException(status_code=409, detail=e.detail) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e
    finally:
        state.release()

    return {"validated": True, "flown": True, "events": events}


@app.post("/flight/stop")
def stop_flight() -> dict:
    """Abort whatever is happening. Always succeeds — a stop that can fail is
    not a stop."""
    if state.manual is not None:
        state.manual.panic()
    state.release()
    return {"stopped": True}


# ── manual control ───────────────────────────────────────────────────────


@app.websocket("/ws/manual")
async def manual_socket(websocket: WebSocket) -> None:
    """Manual flight.

    The client sends held-key state and a periodic heartbeat; the agent runs
    the 50 Hz setpoint loop itself. If this socket goes quiet the controller
    lands the drone without needing to be told.
    """
    # Before accept, before touching the radio. See BUILTIN_ORIGINS.
    origin = websocket.headers.get("origin")
    if not origin_permitted(origin):
        log.warning("refused manual control from origin %r", origin)
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()

    if state.busy:
        await websocket.send_json({"error": f"drone busy with {state.current}"})
        await websocket.close()
        return

    controller: ManualController | None = None
    try:
        with core.connect(state.uri) as scf:
            core._configure(scf.cf)
            controller = ManualController(scf.cf.commander)
            state.manual = controller
            state.claim("manual control")
            controller.start()

            await websocket.send_json({"ready": True})

            while True:
                message = await websocket.receive_json()
                kind = message.get("type")

                if kind == "intent":
                    try:
                        controller.set_intent(Intent.from_payload(message.get("keys", {})))
                    except ValueError as e:
                        # Reject the frame, keep flying. Dropping the link over
                        # a bad message would be worse than ignoring it.
                        controller.stats.rejected_frames += 1
                        await websocket.send_json({"error": str(e)})
                elif kind == "heartbeat":
                    controller.heartbeat()
                elif kind == "panic":
                    controller.panic()
                    await websocket.send_json({"state": str(controller.state)})
                elif kind == "land":
                    controller.land()
                else:
                    controller.stats.rejected_frames += 1
                    await websocket.send_json({"error": f"unknown frame type: {kind!r}"})

                await websocket.send_json({
                    "state": str(controller.state),
                    "thrust": controller.thrust,
                })

    except WebSocketDisconnect:
        # The expected exit: the operator closed the tab. The controller's
        # heartbeat timeout lands the drone; stopping it here does so at once.
        log.info("manual socket disconnected")
    except Exception:
        log.exception("manual socket failed")
    finally:
        if controller is not None:
            controller.stop()
        state.manual = None
        state.release()


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
    process that actually matters. Motors are cut before exiting — this path
    can run while the drone is in the air.
    """
    def watch() -> None:
        try:
            # Returns "" only at EOF. A terminal simply blocks here forever,
            # which is why this is opt-in and never affects interactive use.
            while sys.stdin.readline():
                pass
        except Exception:  # noqa: BLE001 - a closed pipe must not raise here
            pass

        log.warning("parent process closed — cutting motors and exiting")
        if state.manual is not None:
            state.manual.panic()
        # Hard exit: uvicorn's graceful path waits on connections, and this
        # runs when the operator's window is already gone.
        os._exit(0)

    threading.Thread(target=watch, daemon=True, name="parent-watchdog").start()


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    exit_with_parent: bool = False,
) -> None:
    """Run the API. Binding beyond localhost is deliberate — see module docs."""
    import uvicorn

    if host not in {"127.0.0.1", "localhost"}:
        log.warning(
            "binding to %s — this API can arm a drone and has no authentication. "
            "Only do this on a trusted network.", host
        )
    if exit_with_parent:
        exit_when_parent_closes()
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = ["app", "serve", "exit_when_parent_closes", "asyncio"]
