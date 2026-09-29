# Docs router

One line per doc. Read this first, then open only what your work touches.
Feature docs are plain `.txt`, grouped by the surface they describe.

## Start here — the whole system

| Doc | What it covers |
|---|---|
| [features/architecture-at-a-glance.txt](features/architecture-at-a-glance.txt) | **The short version**: components, tech, connections, the numbers. One screen |
| [features/architecture.txt](features/architecture.txt) | The long version: the flows end to end, the layers, the decisions, and which arrows are designed but not wired |

## Backend — the flight agent (`backend/agent/`)

| Doc | What it covers |
|---|---|
| [features/backend/flight-status.txt](features/backend/flight-status.txt) | **Where flight actually is**: every symptom diagnosed, what is proven, what has never flown |
| [features/backend/flight-safety.txt](features/backend/flight-safety.txt) | The pre-flight checks and the in-flight guards. **Read this one first** |
| [features/backend/telemetry-stream.txt](features/backend/telemetry-stream.txt) | The single 10 Hz subscription every reader shares |
| [features/backend/sessions-and-modes.txt](features/backend/sessions-and-modes.txt) | The session state machine, Auto and Manual, ending an operation |
| [features/backend/manual-control.txt](features/backend/manual-control.txt) | Assisted manual flight from held keys, the 50 Hz loop, holding the spot |
| [features/backend/agent-api.txt](features/backend/agent-api.txt) | The local HTTP/WebSocket surface, the control token, CORS |
| [features/backend/offline-sync.txt](features/backend/offline-sync.txt) | The outbox, CSV-first recording, idempotent upload |
| [features/backend/audit-trail.txt](features/backend/audit-trail.txt) | Every action and safety decision, against a person and a drone |
| [features/backend/flight-tuning.txt](features/backend/flight-tuning.txt) | Why the drone bounced and spun, the tuning applied per flight, the 10 Hz trace |
| [features/backend/session-history.txt](features/backend/session-history.txt) | Every session kept on the laptop; Auto/Manual filtered per reading |
| [features/backend/running-from-source.txt](features/backend/running-from-source.txt) | Running the agent from a terminal, for developers — not something operators set up |

## Desktop — the Tauri app (`desktop/`)

| Doc | What it covers |
|---|---|
| [features/desktop/desktop-app.txt](features/desktop/desktop-app.txt) | The shell, the bundled agent sidecar, installers and CI |
| [features/desktop/camera.txt](features/desktop/camera.txt) | The camera path — test pattern and the AI deck's Wi-Fi stream; the deck has not yet delivered a whole frame |
| [features/desktop/setup.txt](features/desktop/setup.txt) | The Set up page: install the camera software on a new drone, then Wi-Fi, then a session |
| [features/desktop/drone-wifi.txt](features/desktop/drone-wifi.txt) | The drone's camera joins the operator's Wi-Fi, set over the radio: the firmware addition, the flasher, the dialog |
| [features/desktop/pages-and-windows.txt](features/desktop/pages-and-windows.txt) | The sidebar shell, Control's two columns and its console, the five live sensor windows, and how the layout is measured |
| [features/desktop/auto-control.txt](features/desktop/auto-control.txt) | Control in Auto: ① Mission (plan, edit, pick) → ② Check → ③ Fly, the monitor on the right |

## Missions — autonomous flight (`backend/agent/cropwatcher/mission/`)

| Doc | What it covers |
|---|---|
| [features/missions/README.txt](features/missions/README.txt) | The index: what to fly, and how it is flown |
| [features/missions/floor-plans.txt](features/missions/floor-plans.txt) | Rooms (closed geofence, obstacles, the room's map), missions, inspection points, the agent's checks, saving |
| [features/missions/mission-controller.txt](features/missions/mission-controller.txt) | How a mission flies: fly_to in the manual system, run_mission, point_id stamping; the controller body is Hannah's |

## Pipeline — the data pipeline (`backend/agent/cropwatcher/pipeline/`)

| Doc | What it covers |
|---|---|
| [features/pipeline/data-pipeline.txt](features/pipeline/data-pipeline.txt) | `cropwatcher process`: clean → enhance → classify → interpret, a verdict per inspection point, laptop-first |

## Frontend — the web app (`web/`)

| Doc | What it covers |
|---|---|
| [features/frontend/operator-dashboard.txt](features/frontend/operator-dashboard.txt) | The `/app` pages: live, flights, zones, compare, settings |
| [features/frontend/mission-planner.txt](features/frontend/mission-planner.txt) | Building, validating, queuing and cancelling missions |
| [features/frontend/portfolio.txt](features/frontend/portfolio.txt) | Public projects and team pages, and the /admin that edits them |
| [features/frontend/gallery.txt](features/frontend/gallery.txt) | Albums of photos and videos, and the admin that manages them |
| [features/frontend/site-pages-and-views.txt](features/frontend/site-pages-and-views.txt) | Editable wording for every page; visitor vs. operator view, Dashboard |

## Supabase — the database (`backend/supabase/`)

| Doc | What it covers |
|---|---|
| [features/supabase/data-model.txt](features/supabase/data-model.txt) | The tables and what ties them together |
| [features/supabase/rls-and-grants.txt](features/supabase/rls-and-grants.txt) | Authorization, and the 15-check proof that it holds |
| [features/supabase/accounts-and-roles.txt](features/supabase/accounts-and-roles.txt) | One account for web and desktop; creating an operator |
| [features/supabase/storage-and-backfill.txt](features/supabase/storage-and-backfill.txt) | The two buckets and the CSV backfill |

## Development — how work here is done

| Doc | What it covers |
|---|---|
| [features/development/skills.txt](features/development/skills.txt) | The `/feature`, `/copy-adapt`, `/preflight` and `/adapt` commands and the feature-kit, committed in `.claude/` so a cloud session has them |
| [features/development/releases.txt](features/development/releases.txt) | How a merge to main becomes a download on /apps, on both platforms |

## The project's working memory — read before starting

Committed so a Claude Code cloud session starts where a local one stopped.

| Doc | What it covers |
|---|---|
| [PROJECT_PROFILE.txt](PROJECT_PROFILE.txt) | The repo, its surfaces, gates, conventions and ship rules |
| [GRAPH_STATE.txt](GRAPH_STATE.txt) | Which docs can be trusted right now — `python3 docs/graph_check.py` regenerates the findings |
| [design/PREFERENCES.txt](design/PREFERENCES.txt) | What the owner asked for more than once, and the rules that became standing |
| [design/components.txt](design/components.txt) | The shared building blocks to reach for first (not filled in yet) |

## The lab

[flight-log.txt](flight-log.txt) — what was flown, what it measured, and what changed
because of it. Newest session first, plus the test ladder every session follows. The one
doc here that is deliberately a journal: flight work cannot be re-run, so the readings
are the only thing that survives a session.

## Plans

[plans/2026-09-16-sessions-flight-portfolio.txt](plans/2026-09-16-sessions-flight-portfolio.txt) — the 70-stage plan for sessions, barometer flight, the desktop redesign and the portfolio.

[plans/2026-09-22-desktop-ui-redesign.txt](plans/2026-09-22-desktop-ui-redesign.txt) — the 100-stage plan for the desktop sidebar shell, the two-column Control page and its three console tabs. What shipped is in [features/desktop/pages-and-windows.txt](features/desktop/pages-and-windows.txt).

[plans/2026-09-25-any-machine-desktop.txt](plans/2026-09-25-any-machine-desktop.txt) — the 50-stage plan that made the desktop app build, run and explain its failures on any Mac or Windows PC: one setup command, one build path, the Windows radio driver, the Intel installer.

[plans/2026-09-25-linux.txt](plans/2026-09-25-linux.txt) — the 40-stage plan that brought the terminal install, a real sign-in check and the radio's USB permission to Linux.

[plans/2026-09-28-missions-and-pipeline.txt](plans/2026-09-28-missions-and-pipeline.txt) — the 100-stage plan for autonomous missions (floor plans, the mission controller through the manual system), the data pipeline, and the Control page remodelled for Auto. What shipped is in features/missions/, features/pipeline/ and features/desktop/auto-control.txt.

## Handoffs — work orders given to teammates

[handoffs/](handoffs/README.txt) — one ticket per piece of work handed to someone else: the mission controller (Hannah), and the data pipeline's clean and enhance (Kevin) and classify (Reagan) stages with the contract they share. Not feature docs: each is deleted once its owner writes what shipped into `features/`.

## Platform — not written yet

`platform/architecture.md`, `platform/flight-safety.md` (superseded by the
backend doc above), `platform/temperature-correction.md` and
`platform/data-model.md` do not exist. CLAUDE.md names the temperature
constants' source; the engine itself is
`backend/agent/cropwatcher/telemetry/correction.py`.

## Hardware

[hardware/](hardware/) — photos of the actual kit, plus the previous team's capstone
report and owner's manual as reference PDFs. The photos are the only record of what the
kit contains; `01`–`02` are the mainboard, `03`–`04` the AI deck, `05` the Crazyradio,
`06`–`10` power and spares.

Note the Lighthouse deck appears in **none** of the photos but **is** fitted —
confirmed by querying `deck.bcLighthouse4` on the drone. Trust the drone, not
the photos.
