# Docs router

One line per doc. Read this first, then open only what your work touches.

## Platform — technical rules that cut across features

| Doc | What it covers |
|---|---|
| [platform/agent-api.md](platform/agent-api.md) | Agent HTTP/WebSocket API, origin checks, the 50 Hz loop |
| platform/architecture.md | **Not written.** Why the agent owns the radio — see CLAUDE.md meanwhile |
| platform/flight-safety.md | **Not written.** Preflight gates, arming, abort, auto-land |
| platform/temperature-correction.md | **Not written.** CLAUDE.md names this as the source for the tuned constants; the engine itself is `backend/agent/cropwatcher/telemetry/correction.py` |
| platform/data-model.md | **Not written.** Tables and RLS — read `backend/supabase/migrations/` |

## Features — product capabilities

| Doc | What it covers |
|---|---|
| [features/operator-dashboard.md](features/operator-dashboard.md) | The `/app` pages: live, flights, zones, compare, manual, settings |
| [features/mission-planner.md](features/mission-planner.md) | Building, validating, queuing and cancelling missions |
| [features/desktop-app.md](features/desktop-app.md) | Tauri app, the agent sidecar, installers and CI |

## Hardware

[hardware/](hardware/) — photos of the actual kit, plus the previous team's capstone
report and owner's manual as reference PDFs. The photos are the only record of what the
kit contains; `01`–`02` are the mainboard, `03`–`04` the AI deck, `05` the Crazyradio,
`06`–`10` power and spares.

Note the Lighthouse deck appears in **none** of the photos but **is** fitted — confirmed
by querying `deck.bcLighthouse4` on the drone. Trust the drone, not the photos.
