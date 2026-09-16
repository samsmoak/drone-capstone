# Mission planner

**What it is.** `/app/plan`: click zones in the order to visit them, set
altitude and hold time, and queue the mission in Supabase for the agent to
claim and fly. Also lists recent missions and cancels queued ones.

**Where it lives.** `lib/mission-plan.ts` (build + validate, shared by browser
and server), `lib/mutations.ts::queuePlannedMission` and `cancelMission`,
`components/mission-planner.tsx`, `components/mission-queue.tsx`. The plan
format is the agent's `Mission.to_dict()` in
`backend/agent/cropwatcher/flight/missions.py`.

## Decisions

- **The server action takes zone ids and settings, never waypoints.** It rebuilds
  the plan from its own zones table and validates it. A Server Action is a public
  endpoint; only what the server builds reaches the agent. The earlier
  `queueMission(plan)`, which inserted any object, was removed unused.
- **Validation runs twice, and neither is the safety gate.** The planner and the
  action run `validatePlan` so problems appear while planning; the agent
  re-validates against its geofence and occupancy map before arming.
- **Leg duration comes from the longest leg at 0.5 m/s** (minimum 3 s). The agent
  flies every leg in one `leg_duration_s`; its 3 s default across a 4 m leg is
  1.3 m/s indoors. *0.5 m/s is an assumption, not a measured limit.*
- **The planner's fence is ±2.0 m**, mirroring the agent's `--fence` default.
  Starting the agent with another value does not update the planner.

## Invariants

- **Waypoint x and y are absolute Lighthouse metres; only z is ground-relative.**
  `Flight.goto` sends `go_to(wp.x, wp.y, ground_z + wp.z)`. The `Mission`
  docstring says "relative to the takeoff point" — that is true for z only. A
  zone's centre is therefore a waypoint as-is. Verified: a planner-queued plan
  loads and validates through the agent's own `Mission.from_dict`.
- **Count the rows a cancel changed.** An update matching nothing is not an error
  to Postgres. Without the count, a mission the agent claimed a moment earlier
  was reported "cancelled" and then flew. Verified with a claim injected between
  page load and click: the row stays `claimed`, the operator is told it was not
  cancelled.
