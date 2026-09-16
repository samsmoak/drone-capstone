# Operator dashboard

**What it is.** The signed-in area of the web app, `/app/*`: live telemetry,
recorded flights, zone health, flight comparison, mission planning, manual
control and settings.

**Where it lives.**

| Route | Page | Key pieces |
|---|---|---|
| `/app/live` | `app/app/live/page.tsx` | `components/live-view.tsx`, `lib/use-live-telemetry.ts`, `lib/store.ts` |
| `/app/flights`, `/[id]` | `app/app/flights/` | `components/ui/time-series.tsx`, `flight-path.tsx`, `raw-readings.tsx` |
| `/app/zones` | `app/app/zones/page.tsx` | `components/ui/zone-map.tsx` |
| `/app/compare` | `app/app/compare/page.tsx` | `lib/compare.ts` |
| `/app/plan` | `app/app/plan/page.tsx` | see [mission-planner.md](mission-planner.md) |
| `/app/manual` | `app/app/manual/page.tsx` | `components/manual-control.tsx` |
| `/app/settings` | `app/app/settings/page.tsx` | `components/agent-reachability.tsx` |

Shared: `app/app/error.tsx`, `app/app/loading.tsx`, `components/ui/page-header.tsx`,
`components/ui/local-time.tsx`, `lib/flight-format.ts`.

## Decisions

- **One chart component, `TimeSeries`, with no second-axis seam.** Different
  units are different charts. It always ships a table view, because light-mode
  `--series-3` and `--series-4` are under 3:1 (re-measured: 2.74 and 2.11).
- **Compare keeps each flight's colour in the URL** (`?f=<id>:<slot>`), so
  removing one flight never repaints the others. Four flights maximum, matching
  the four validated series colours.
- **Settings is read-only.** The geofence the drone obeys is the agent's
  `--fence` flag; a browser-stored value would change nothing while looking as
  if it had. Each value says where it really lives.
- **Manual control in the browser is a port of the desktop client** — same frame
  contract, same key map. Some browsers will not let an https page open
  `ws://127.0.0.1`; the page says so and points to the desktop app.

## Invariants

- **Reads throw; they never return `data ?? []`.** An empty fallback rendered a
  database error as "No flights recorded yet". `QueryError` logs the Postgres
  message server-side and `error.tsx` shows a retry.
- **Set the Realtime token before subscribing.** The SSR browser client loads
  its session lazily; a channel joined first subscribes as `anon`, RLS delivers
  nothing, and the channel still reports `SUBSCRIBED`. Measured: 0 rows in 5 s
  from the page versus 16/16 from a client that set the token.
- **Backfill after subscribing.** Rows written between the server read and the
  socket opening arrive on neither; `useLiveTelemetry` fetches everything after
  the last index it holds once subscribed.
- **Format times in the browser (`<LocalTime>`).** `toLocaleString()` in a Server
  Component uses the server's zone — UTC on Vercel — so 4:45 PM Eastern rendered
  as 8:45 PM with no label. Before hydration it prints an explicit `UTC` time.
- **Y-axes fit the data with computed ticks.** Recharts' zero baseline flattened
  3.7–4.1 V into a line; its own ticks inside a domain were uneven, and a domain
  *function* drew no axis for some ranges.
- **Text in charts uses `--muted`, never `--axis`.** `--axis` measures 2.86:1
  (light) / 2.94:1 (dark) — it is for lines only. Legend text is forced to
  `--foreground`; Recharts colours it with the series by default.
- **Height is ground-relative or not shown as height.** Without `ground_z_m`, raw
  Lighthouse z is labelled as such, and Compare leaves the flight out — floor
  level varied 0.85–1.40 m between runs.
- **The nav marks the longest matching route active.** A prefix test marked
  `/app` active on every page.
