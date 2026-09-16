# Agent API

**What it is.** The flight agent's local HTTP and WebSocket API — what the desktop
app and the browser talk to. `backend/agent/cropwatcher/api/rest.py` (routes,
origin checks) and `api/manual.py` (the 50 Hz manual-control loop). Served by
`cropwatcher serve`; `python -m cropwatcher.api.rest` does nothing, the module has
no entry point.

| Surface | Purpose |
|---|---|
| `GET /health`, `/status`, `/preflight` | Liveness, radio scan, gates without spinning a motor |
| `POST /flight/mission`, `/flight/stop` | Fly a plan; stop — always succeeds |
| `WS /ws/manual` | Held-key intent in, `{state, thrust}` out |

## Decisions

- **Binds to 127.0.0.1 by default.** It can arm a drone and has no authentication.
- **CORS allows `GET` only, from a fixed origin list.** The dashboard needs to see
  whether the agent is running; no web page should be able to start a flight. A
  bodyless `POST /flight/stop` is a CORS "simple request" and works regardless —
  acceptable, because stop is the safe direction.
- **Origins:** the production site, `localhost:3000`, and the three Tauri
  origins. Extend with `CROPWATCHER_ALLOWED_ORIGINS` (comma-separated) for a
  preview deployment; never with `*`.

## Invariants

- **Localhost does not keep websites out.** Every page an operator has open can
  reach 127.0.0.1, and WebSockets are not covered by CORS. Without its own
  `Origin` check, any site could open `/ws/manual` and fly the drone. The socket
  refuses unknown origins with close code 1008 *before* touching the radio. A
  missing `Origin` is allowed: browsers always send one, so its absence means a
  local script or the CLI.
- **The browser-facing endpoints need CORS, including `allow_private_network`.**
  Before it was added, `/health` answered with no `Access-Control-Allow-Origin`
  and the preflight got a 405 — so a browser discards the response, and the
  `/setup` banner could only ever say "not running". Chrome's Private Network
  Access preflight from a public https page needs its own answer. The fetch from
  the live site has not yet been tried against a running agent.
- **The manual loop schedules by deadline, not by sleep.** Sleeping `tick_s`
  after each tick measured 38 Hz against a recording commander; deadline
  scheduling measured 50 Hz end to end from the browser. It resyncs rather than
  bursting if it falls a tick behind. `test_holds_fifty_hertz_in_real_time`
  fails on the old loop.
- **Manual control records no telemetry.** `/ws/manual` starts no
  `TelemetryReader`, so a manually flown flight writes no CSV and no rows. And
  `serve` does not run the mission poller — missions queued on the web are flown
  only by a separate `cropwatcher poll` process.
- **`--exit-with-parent` cuts motors and exits when stdin closes.** Used by the
  desktop app; see [desktop-app.md](../features/desktop-app.md) for why killing
  the process is not enough.
