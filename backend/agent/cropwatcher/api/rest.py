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
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from cropwatcher.api.manual import Intent, ManualController
from cropwatcher.flight import core, missions
from cropwatcher.flight.missions import Mission, MissionValidationError
from cropwatcher.flight.preflight import PreflightError
from cropwatcher.safety.geofence import Geofence

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


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


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the API. Binding beyond localhost is deliberate — see module docs."""
    import uvicorn

    if host not in {"127.0.0.1", "localhost"}:
        log.warning(
            "binding to %s — this API can arm a drone and has no authentication. "
            "Only do this on a trusted network.", host
        )
    uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = ["app", "serve", "asyncio"]
