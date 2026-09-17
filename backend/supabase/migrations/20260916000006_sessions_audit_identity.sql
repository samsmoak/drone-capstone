-- Sessions, the audit trail, drone identity, and the telemetry the live
-- windows show.
--
-- Everything here exists so a flight can answer four questions for all time:
-- who flew it, which drone, what happened, and what the sensors read.
--
-- Idempotent throughout: safe to re-run, and safe on a database whose schema
-- was applied by hand (as the hosted project's was).


-- ── drone identity ──────────────────────────────────────────────────────
--
-- Identified by the MCU id the drone reports (`cpu.id0..2`), not by radio
-- address: two Crazyflies ship with the same default address, so tagging
-- flights by address would mix two drones' data into one history.

alter table public.drones add column if not exists hardware_id text;
create unique index if not exists drones_hardware_id_key
  on public.drones (hardware_id) where hardware_id is not null;

-- The agent registers a drone the first time it meets one. Read-only before
-- this migration, so a new drone could never be recorded.
drop policy if exists "operators register drones" on public.drones;
create policy "operators register drones"
  on public.drones for insert to authenticated
  with check (public.is_operator());

drop policy if exists "operators update drones" on public.drones;
create policy "operators update drones"
  on public.drones for update to authenticated
  using (public.is_operator()) with check (public.is_operator());


-- ── sessions ────────────────────────────────────────────────────────────
--
-- One operator, one drone, from Start session to End session. Flights hang off
-- it, so "who was on duty" is answerable even for a mission someone else queued
-- from the web.

create table if not exists public.sessions (
  id             uuid primary key,          -- generated on the laptop, so an
                                            -- offline session already has its id
  operator_id    uuid references public.profiles (id),
  drone_id       uuid references public.drones (id),
  agent_id       text,
  mode_at_start  text,
  started_at     timestamptz not null default now(),
  ended_at       timestamptz,
  end_reason     text
);

create index if not exists sessions_operator_idx on public.sessions (operator_id, started_at desc);

alter table public.sessions enable row level security;

drop policy if exists "signed-in read sessions" on public.sessions;
create policy "signed-in read sessions"
  on public.sessions for select to authenticated using (true);

drop policy if exists "operators record their own sessions" on public.sessions;
create policy "operators record their own sessions"
  on public.sessions for insert to authenticated
  with check (public.is_operator() and operator_id = auth.uid());

drop policy if exists "operators update their own sessions" on public.sessions;
create policy "operators update their own sessions"
  on public.sessions for update to authenticated
  using (public.is_operator() and operator_id = auth.uid())
  with check (public.is_operator() and operator_id = auth.uid());


-- ── flights: which session, which mode, how it ended ────────────────────

alter table public.flights add column if not exists session_id uuid references public.sessions (id);
alter table public.flights add column if not exists mode text;
alter table public.flights add column if not exists program text;
alter table public.flights add column if not exists outcome text;
alter table public.flights add column if not exists abort_reason text;

create index if not exists flights_session_idx on public.flights (session_id);


-- ── telemetry: exactly once, and the live sensor columns ────────────────
--
-- The unique key is what makes re-uploading safe. Without it, a laptop that
-- came back online and re-sent a batch would store every row twice; with it,
-- the agent and the server-side import can both push the same file.

create unique index if not exists telemetry_flight_index_key
  on public.telemetry (flight_id, index);

alter table public.telemetry add column if not exists vx_m_s double precision;
alter table public.telemetry add column if not exists vy_m_s double precision;
alter table public.telemetry add column if not exists vz_m_s double precision;
alter table public.telemetry add column if not exists roll_deg double precision;
alter table public.telemetry add column if not exists pitch_deg double precision;
alter table public.telemetry add column if not exists yaw_deg double precision;
alter table public.telemetry add column if not exists acc_x_g double precision;
alter table public.telemetry add column if not exists acc_y_g double precision;
alter table public.telemetry add column if not exists acc_z_g double precision;
alter table public.telemetry add column if not exists gyro_x_deg_s double precision;
alter table public.telemetry add column if not exists gyro_y_deg_s double precision;
alter table public.telemetry add column if not exists gyro_z_deg_s double precision;
alter table public.telemetry add column if not exists motor_m1 integer;
alter table public.telemetry add column if not exists motor_m2 integer;
alter table public.telemetry add column if not exists motor_m3 integer;
alter table public.telemetry add column if not exists motor_m4 integer;
alter table public.telemetry add column if not exists lighthouse_received integer;


-- ── audit events ────────────────────────────────────────────────────────
--
-- Append-only by construction: there is no update or delete policy, for
-- operators or anyone else. Editing history is not a feature.
--
-- Deliberately **no foreign keys** to flights, sessions or drones. A laptop
-- that was offline uploads its events first, before the flight they describe,
-- and a foreign key would reject them for arriving in the honest order.

create table if not exists public.audit_events (
  id                 uuid primary key,      -- made on the laptop; re-sending
                                            -- the same event changes nothing
  occurred_at        timestamptz not null default now(),
  actor_id           uuid not null default auth.uid() references public.profiles (id),
  actor_email        text,
  source             text not null check (source in ('desktop', 'web', 'server')),
  action             text not null,
  result             text not null default 'ok' check (result in ('ok', 'refused', 'failed', 'aborted')),
  session_id         uuid,
  flight_id          uuid,
  mission_id         uuid,
  drone_hardware_id  text,
  detail             jsonb not null default '{}'::jsonb
);

create index if not exists audit_events_time_idx on public.audit_events (occurred_at desc);
create index if not exists audit_events_actor_idx on public.audit_events (actor_id, occurred_at desc);
create index if not exists audit_events_action_idx on public.audit_events (action, occurred_at desc);

alter table public.audit_events enable row level security;

-- Anyone signed in may record what *they* did; nobody may write history for
-- someone else.
drop policy if exists "record your own actions" on public.audit_events;
create policy "record your own actions"
  on public.audit_events for insert to authenticated
  with check (actor_id = auth.uid());

drop policy if exists "operators read the audit trail" on public.audit_events;
create policy "operators read the audit trail"
  on public.audit_events for select to authenticated
  using (public.is_operator());


-- ── claiming one specific mission ───────────────────────────────────────
--
-- `claim_next_mission` takes whatever is at the head of the queue. The desktop
-- app shows the operator the queue and they pick one, having confirmed the
-- area for that flight — so it claims by id, still atomically, still only if
-- the mission is still queued.

create or replace function public.claim_mission(mission_id uuid, agent_id text)
returns public.missions
language sql
security invoker
set search_path = public
as $$
  update public.missions
     set status = 'claimed', claimed_by = agent_id, claimed_at = now(), updated_at = now()
   where id = mission_id
     and status = 'queued'
  returning *;
$$;

grant execute on function public.claim_mission(uuid, text) to authenticated;


-- ── privileges ──────────────────────────────────────────────────────────
-- Explicit, per migration 0004: the platform's defaults differ between a local
-- stack and a hosted project, so nothing is left to them.

grant select, insert, update on public.sessions to authenticated;

-- A drone registers itself on first connect. Migration 0004 revoked everything
-- and re-granted only SELECT here, so the "operators register drones" policy
-- above was a policy with no privilege behind it — the insert was refused with
-- "permission denied for table drones", not by RLS.
grant select, insert, update on public.drones to authenticated;

-- Audit events: insert and read only. The absence of an UPDATE policy already
-- means RLS matches no rows, but the privilege itself is revoked as well — a
-- local database was found holding an UPDATE grant nobody in this repo issued,
-- which is the same platform-defaults problem migration 0004 documents.
grant select, insert on public.audit_events to authenticated;
revoke update, delete on public.audit_events from authenticated;

revoke all on public.sessions from anon;
revoke all on public.audit_events from anon;


-- ── flight log storage ──────────────────────────────────────────────────
--
-- Private: a flight log is operator data. CI's installer bucket is public;
-- this one is not.

insert into storage.buckets (id, name, public)
values ('flight-logs', 'flight-logs', false)
on conflict (id) do update set public = excluded.public;

drop policy if exists "operators upload flight logs" on storage.objects;
create policy "operators upload flight logs"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'flight-logs' and public.is_operator());

drop policy if exists "operators read flight logs" on storage.objects;
create policy "operators read flight logs"
  on storage.objects for select to authenticated
  using (bucket_id = 'flight-logs' and public.is_operator());
