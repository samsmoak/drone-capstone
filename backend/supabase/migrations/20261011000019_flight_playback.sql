-- ── flight_plans, flight_traces: what playback needs that telemetry lacks ──
--
-- Mission playback (docs/features/desktop/mission-playback.txt) replays a
-- recorded flight on the room map. public.telemetry already holds where the
-- drone was and what it read, for every flight. Two things never left the
-- laptop that flew, so another computer could not replay a mission:
--
--   flight_plans   the plan AS FLOWN — the mission after auto-correct, from
--                  the drone's real start — and its room (agent
--                  session._keep_plan_flown, sessions/<id>/missions/<flight>.json)
--   flight_traces  the 10 Hz control trace (agent telemetry/trace.py,
--                  flights/<day>/trace_<id8>.csv): the loop's state, the keys
--                  the operator held, where it was sending the drone, drift
--
-- Both are a record of what happened, uploaded after the flight from files
-- the laptop wrote first (CLAUDE.md invariant 6). Like telemetry they are
-- APPEND-ONLY: read by every signed-in user (everyone's flights play back),
-- written only by an operator, only for a flight that is theirs, never edited
-- or deleted. A re-sent row changes nothing (primary keys + ignore-duplicates).

create table if not exists public.flight_plans (
  flight_id   uuid primary key references public.flights (id) on delete cascade,
  mission     jsonb not null,                    -- Mission.to_dict(), as flown
  room        jsonb,                             -- Room.to_dict(); null if none was kept
  moves       jsonb not null default '[]'::jsonb, -- points auto-correct moved
  created_at  timestamptz not null default now()
);

create table if not exists public.flight_traces (
  flight_id        uuid not null references public.flights (id) on delete cascade,
  seq              integer not null,              -- the row in the trace CSV, from 1
  recorded_at      timestamptz not null,
  control_state    text,                          -- armed, flying, landing, landed, …
  keys             text,                          -- the keys held, as recorded
  target_x_m       double precision,              -- where the loop sent the drone
  target_y_m       double precision,
  target_height_m  double precision,              -- above the takeoff floor
  drift_m          double precision,
  height_error_m   double precision,              -- stateEstimate.z − posCtl.targetZ
  "values"         jsonb not null default '{}'::jsonb, -- every other trace column
  primary key (flight_id, seq)
);

create index if not exists flight_traces_time_idx
  on public.flight_traces (flight_id, recorded_at);

alter table public.flight_plans  enable row level security;
alter table public.flight_traces enable row level security;

drop policy if exists "signed-in read flight plans" on public.flight_plans;
create policy "signed-in read flight plans"
  on public.flight_plans for select to authenticated using (true);

drop policy if exists "signed-in read flight traces" on public.flight_traces;
create policy "signed-in read flight traces"
  on public.flight_traces for select to authenticated using (true);

-- An operator uploads a plan or a trace only for a flight they flew.
drop policy if exists "operators write their own flight plans" on public.flight_plans;
create policy "operators write their own flight plans"
  on public.flight_plans for insert to authenticated
  with check (
    public.is_operator()
    and exists (select 1 from public.flights f
                where f.id = flight_id and f.created_by = auth.uid())
  );

drop policy if exists "operators write their own flight traces" on public.flight_traces;
create policy "operators write their own flight traces"
  on public.flight_traces for insert to authenticated
  with check (
    public.is_operator()
    and exists (select 1 from public.flights f
                where f.id = flight_id and f.created_by = auth.uid())
  );

-- A policy without a grant is a 403 (20261008000014, rls-and-grants.txt):
-- this project revokes the platform's default privileges, so grant exactly
-- what telemetry has — read and append for signed-in users, nothing more,
-- nothing for anon. No update or delete: the record is append-only.
revoke all on public.flight_plans, public.flight_traces from anon, authenticated;
grant select, insert on public.flight_plans, public.flight_traces to authenticated;
