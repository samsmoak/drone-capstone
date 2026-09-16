# CLAUDE.md

> **Picking this up fresh? Read `NEXT-STEPS.txt` at the repo root** — it lists
> exactly what is built, what is not, and what to do next.

**drone-capstone** — CropWatcher: an indoor greenhouse crop-health monitoring system built
around a Crazyflie 2.1. The drone flies autonomous scouting missions, logs position-tagged
environmental data, and surfaces it as zone-level crop-health estimates in a web dashboard.

## The constraint everything follows from

**The Crazyradio is a USB dongle. Only the machine it is plugged into can command the
drone.** No cloud service can reach it. Every architectural decision here is downstream of
that one fact.

```
browser ──▶ Supabase ──poll──▶ agent ──radio──▶ drone     (autonomous: delay is harmless)
browser ──────── WebSocket, same network ─────▶ agent     (manual: needs 50 Hz)
```

The agent is the only process that touches the radio. Nothing else — ever.

## Layout

| Path | What | Runs where |
|---|---|---|
| `backend/agent/` | Python · FastAPI · cflib | The laptop with the dongle |
| `backend/supabase/` | Migrations, seed, RLS | Supabase cloud |
| `web/` | Next.js 16 · React 19 · Tailwind v4 · Zustand | Vercel |
| `desktop/` | Tauri v2 — manual control, bundles the agent | User's laptop |
| `docs/hardware/` | Kit photos + the two reference PDFs | — |

`backend/` nests `supabase/` rather than renaming it: the Supabase CLI resolves
`supabase/` relative to the working directory, so run it as `cd backend && supabase ...`.

## Commands

```bash
# agent
cd backend/agent && source .venv/bin/activate
pytest                                    # gate
python -m cropwatcher.api.rest            # serve

# web
cd web && pnpm dev
pnpm typecheck && pnpm lint && pnpm build # gates
```

## Flight invariants

These cost real debugging time to discover. Each is a rule, with the failure it prevents.

1. **Read `sys.canfly` before commanding flight.** The firmware supervisor refuses to arm
   below roughly 3.75 V and reports this itself. Do not invent a voltage threshold — a
   guessed 3.70 V refused flights the drone would have allowed, repeatedly.

2. **Call `send_notify_setpoint_stop()` before using the high-level commander.** Any prior
   low-level `send_setpoint()` in the same power cycle holds setpoint priority and
   silently locks out the high-level commander: `takeoff()` returns successfully and the
   motors stay at exactly 0.

3. **Wait for the Kalman estimate to settle after a reset — never a fixed sleep.** The
   estimate keeps converging for seconds afterwards. Sampling too early produced a ground
   reference 0.14 m wrong, which put the takeoff target below the floor. Require the
   spread across a sliding window to fall under ~2 cm before trusting a value.

4. **Lighthouse `z = 0` is not the floor.** Measured floor level ranged 0.85–1.40 m across
   runs in the same room. Always capture ground at takeoff and treat commanded altitude as
   relative to it, or "1 m" becomes a 15 cm hop.

5. **The running system is the authority, not the docs or the photos.** `deck.bcLighthouse4`
   answers "is the positioning deck fitted" definitively; inferring it from kit photos was
   wrong for hours. Query the drone.

6. **Write the CSV first, then upload.** A local write cannot fail; a flight cannot be
   re-run. Supabase upload is best-effort and retried, never in the critical path.

7. **Docker cannot reach USB on macOS.** Docker Desktop runs a Linux VM with no USB
   passthrough, so the agent runs bare in a venv. A `Dockerfile` is for CI and Linux
   teammates only.

## Conventions

- **Units:** metres and seconds internally, everywhere. Feet appear only in UI labels,
  converted at the boundary. Temperature is stored in the unit the operator selected at
  launch, with the unit recorded in the row.
- **Data layer:** all Supabase access goes through `web/lib/queries.ts` (reads,
  `import "server-only"` + React `cache`) and `web/lib/mutations.ts` (writes). Never
  `createClient()` inside a component — it also keeps a future Tauri mobile static export
  viable.
- **Zustand holds only ephemeral live state** — telemetry buffer, socket status, manual
  control state. Anything persistent comes from Supabase.
- **Design tokens:** CSS custom properties on `:root` in `web/app/globals.css`. Raw hex is
  confined to token definitions; components reference the variables only.
- **Authorization is server-side**, enforced by RLS on every table. Client-side checks are
  UX only. The app is publicly reachable and commands a physical drone.

## Deploying

**Vercel's Root Directory must be set to `web`.** Left unset, Vercel scans the
repo root, finds `backend/agent/pyproject.toml`, detects FastAPI and tries to
deploy the flight agent — the build then fails asking for a FastAPI entrypoint.

Never give it one. The agent talks to a USB radio: it cannot run in the cloud,
and deploying it would put operator credentials on a server for no benefit.
`.vercelignore` is a second line of defence, but the Root Directory setting is
the actual fix.

Env vars needed on Vercel: `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_SITE_URL`. The build succeeds
without them — `isSupabaseConfigured()` degrades the operator area rather than
blanking the site — but sign-in will not work until they are set.

## Git

- Commit as **`samsmoaky@gmail.com`**.
- **No Claude co-author or footer lines.** Author is the user only.
- Branch: `main`. Web deploys via Vercel on push.

## Out of scope

The AI deck camera. Its Wi-Fi datalink never worked in the original capstone and was cut
from final scope — the deck is fitted (`deck.bcAI = 1`) but treated as diagnostic only.
Docker for the agent, real-time stick control over the internet, and haptics as a
requirement (`navigator.vibrate` is Android-only) are also out.

## Reference material

`~/Desktop/drone project/` (a separate folder, outside this repo) holds the previous
team's implementation in `code/`, plus the working flight scripts from the bring-up
session. Read-only: consult it, never import from it.

The one thing worth taking verbatim is the tuned temperature-correction constants — see
`docs/platform/temperature-correction.md`. `short_hover.py` there is the reference
implementation for the invariants above; it is the script that achieved the first
successful autonomous hover.
