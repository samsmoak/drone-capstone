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
| [features/development/skills.txt](features/development/skills.txt) | The `/preflight` and `/adapt` commands committed in `.claude/commands/` |
| [features/development/releases.txt](features/development/releases.txt) | How a merge to main becomes a download on /apps, on both platforms |

## The lab

[flight-log.txt](flight-log.txt) — what was flown, what it measured, and what changed
because of it. Newest session first, plus the test ladder every session follows. The one
doc here that is deliberately a journal: flight work cannot be re-run, so the readings
are the only thing that survives a session.

## Plans

[plans/2026-09-16-sessions-flight-portfolio.txt](plans/2026-09-16-sessions-flight-portfolio.txt) — the 70-stage plan for sessions, barometer flight, the desktop redesign and the portfolio.

[plans/2026-09-22-desktop-ui-redesign.txt](plans/2026-09-22-desktop-ui-redesign.txt) — the 100-stage plan for the desktop sidebar shell, the two-column Control page and its three console tabs. What shipped is in [features/desktop/pages-and-windows.txt](features/desktop/pages-and-windows.txt).

[plans/2026-09-25-any-machine-desktop.txt](plans/2026-09-25-any-machine-desktop.txt) — the 50-stage plan that made the desktop app build, run and explain its failures on any Mac or Windows PC: one setup command, one build path, the Windows radio driver, the Intel installer.

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
