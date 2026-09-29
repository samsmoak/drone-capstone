HANDOFFS — work orders for the team
===================================

STATUS: READY. The skeleton every ticket builds against is on main (#72,
2026-09-28; plan: ../plans/2026-09-28-missions-and-pipeline.txt) — start your
branch from main. UPDATED 2026-09-29 for what landed after it (below, and a
dated note at the top of each ticket it changes). Where a ticket and the code
disagree, the code wins — tell Samuel so the ticket is fixed.

A handoff is one piece of work given to one person, written so they can build
it on their own and have it fit when it is plugged into the whole.

HANDOFFS ARE NOT FEATURE DOCS. docs/features/ describes what is built and
verified, and a checker compares it with the code. A ticket describes what
does not exist yet, so it would fail that check. When a ticket is done, its
owner writes what actually shipped into docs/features/ (template:
docs/_templates/feature.txt), then the ticket is deleted. Git keeps the
history.


THE TICKETS

  Ticket                   Owner    Stories (planning PDF)     Can start
  ──────────────────────────────────────────────────────────────────────────────
  mission-planner.txt      Samuel   mission planning; 3.4      built — the
                                    (holds ≥ 5 s)              follow-ups are
                                                               open
  mission-start.txt        Samuel   autonomous flight (the     built — the
                                    session's half)            follow-ups are
                                                               open
  dpp-switch.txt           Samuel   4.5 (the trigger, the      built — the
                                    results on screen)         follow-ups are
                                                               open
  control-layout.txt       Samuel   — (the standing layout     built — the
                                    rule)                      follow-ups are
                                                               open
  mission-controller.txt   Hannah   3.4, 3.5 (flying half),    now
                                    autonomous flight
  dpp-contract.txt         every    4.5                        — (the shared
                           pipeline                            agreement)
                           owner
  dpp-clean.txt            Kevin    4.2                        now
  dpp-enhance.txt          Kevin    4.3 (and the colorize      now
                                    stretch)
  dpp-classify.txt         Reagan   4.4, 4.6 (the classifier   now
                                    half)


WHAT IS ALREADY BUILT — the skeleton everyone plugs into

Mission system (backend/agent/cropwatcher/mission/, docs/features/missions/)
  - plan/: rooms (closed geofence, obstacles, clearance), missions (home,
    inspection points), the agent's validation, saving on the laptop.
  - ManualController.fly_to(), goal_active, operator_override
    (flight/manual.py) — the goal the mission controller drives.
  - controller/: the MissionController INTERFACE, its states and events, and
    a placeholder body that refuses to fly (BUILT = False).
  - Session.run_mission() and POST /session/mission: every refusal before
    anything arms; the room's fence to the in-flight guard; point_id stamped
    into every telemetry row and frames.csv row while holding.
  - tests/fakes.py (FakeCommander, FakeClock); tests/mission/.
  - The desktop Auto page: ① Mission (list, view, edit, save) → ② Check →
    ③ Fly (Start mission, the scene with the mission loaded).
  - 2026-09-29: THE FLIGHT STARTS FROM THE DRONE — Mission.from_start puts
    the start where the drone is, keeps the points, drops points after the
    operator's END POINT, and re-validates; that is what the controller is
    handed (mission-controller.txt, "CHANGED 2026-09-29"). A mission needs at
    least one point to be saved. The desktop draws rooms in 2-D or 3-D;
    obstacles may carry a height (drawn only — never flown over).

Data pipeline (backend/agent/cropwatcher/pipeline/, docs/features/pipeline/)
  - contracts.py — every type in dpp-contract.txt.
  - A stub for clean, enhance and classify; interpret (labels → verdicts).
  - LocalFlightSource, LocalResultSink, the runner, compose.py.
  - `cropwatcher process --flight <id>` and `--fixture`.
  - 2026-09-29: THE DPP SWITCH — with it on, the agent runs that command for
    every flight when it lands, in a child process, and the desktop shows the
    verdicts (dpp-contract.txt, "HOW THE AGENT RUNS THE PIPELINE").
  - tests/pipeline/: a real flight fixture, conformance.py and its checks.


RULES THAT APPLY TO EVERY TICKET

- READ CLAUDE.md AT THE REPO ROOT FIRST. It outranks these tickets. The
  flight invariants are there, and each cost real debugging time.

- SET UP ONCE:
    node scripts/setup.mjs --dev
    cd backend/agent && source .venv/bin/activate

- GATES, ALL THREE, BEFORE EVERY PULL REQUEST, from backend/agent/:
    ruff check . && mypy cropwatcher && pytest
  Report pass or fail honestly in the PR, including failing output.

- GIT: work on the branch named in your ticket, and open a pull request to
  main. Only Samuel can merge into main (a repository rule), so a refused
  push to main is expected. Commit under your own name. No AI co-author or
  footer lines (CLAUDE.md, "Git").

- UNITS: metres and seconds everywhere. Temperatures are stored in the unit
  the operator chose (temp_unit, "C" or "F"), recorded with every flight.
  Never assume Celsius.

- NEVER INVENT A THRESHOLD. Measure it on real data, and write the
  measurement next to the constant (CLAUDE.md, flight invariant 1 and "The
  running system is the authority").

- STUCK, OR THE CONTRACT SEEMS WRONG? Tell Samuel before working around it. A
  private workaround breaks when your part is plugged into the whole.
