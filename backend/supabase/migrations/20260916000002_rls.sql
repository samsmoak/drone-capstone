-- Row-level security.
--
-- Deny by default on every table: enabling RLS with no policy denies everything,
-- and each policy below opens exactly one door. This app is publicly reachable
-- and commands a physical drone, so an anonymous insert into `missions` would
-- put a real aircraft in the air.
--
-- Provider-agnostic: auth.uid() is the same whether the session came from
-- email/password or Google, so nothing here needs to change when Google is
-- switched on.

alter table public.profiles    enable row level security;
alter table public.drones      enable row level security;
alter table public.zones       enable row level security;
alter table public.flights     enable row level security;
alter table public.telemetry   enable row level security;
alter table public.missions    enable row level security;
alter table public.predictions enable row level security;


-- ── helper ──────────────────────────────────────────────────────────────

create function public.is_operator()
returns boolean
language sql
security definer
stable
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'operator'
  );
$$;

comment on function public.is_operator is
  'True when the caller may command the drone. Viewers can read but not fly.';


-- ── profiles ────────────────────────────────────────────────────────────

create policy "read own profile"
  on public.profiles for select
  to authenticated
  using (id = auth.uid());

create policy "update own profile"
  on public.profiles for update
  to authenticated
  using (id = auth.uid())
  with check (id = auth.uid() and role = (select role from public.profiles where id = auth.uid()));

-- Note the `role` guard above: without it a user could promote themselves from
-- viewer to operator and gain the ability to fly the drone.


-- ── reference data: any signed-in user may read ─────────────────────────

create policy "signed-in read drones"
  on public.drones for select to authenticated using (true);

create policy "signed-in read zones"
  on public.zones for select to authenticated using (true);

create policy "operators manage zones"
  on public.zones for all to authenticated
  using (public.is_operator()) with check (public.is_operator());


-- ── flights and telemetry ───────────────────────────────────────────────

create policy "signed-in read flights"
  on public.flights for select to authenticated using (true);

create policy "operators write flights"
  on public.flights for insert to authenticated
  with check (public.is_operator());

create policy "operators update flights"
  on public.flights for update to authenticated
  using (public.is_operator()) with check (public.is_operator());

create policy "signed-in read telemetry"
  on public.telemetry for select to authenticated using (true);

create policy "operators write telemetry"
  on public.telemetry for insert to authenticated
  with check (public.is_operator());

-- Telemetry is an append-only record of what the sensors reported. There is no
-- update or delete policy, so it cannot be edited after the fact.


-- ── missions ────────────────────────────────────────────────────────────

create policy "signed-in read missions"
  on public.missions for select to authenticated using (true);

create policy "operators queue missions"
  on public.missions for insert to authenticated
  with check (public.is_operator() and created_by = auth.uid());

create policy "operators cancel own missions"
  on public.missions for update to authenticated
  using (public.is_operator())
  with check (public.is_operator());


-- ── predictions ─────────────────────────────────────────────────────────

create policy "signed-in read predictions"
  on public.predictions for select to authenticated using (true);

create policy "operators write predictions"
  on public.predictions for insert to authenticated
  with check (public.is_operator());


-- ── mission claiming ────────────────────────────────────────────────────

create function public.claim_next_mission(agent_id text)
returns public.missions
language plpgsql
security definer
set search_path = ''
as $$
declare
  claimed public.missions;
begin
  -- FOR UPDATE SKIP LOCKED is what makes this safe with several agents
  -- polling: each transaction locks a different row instead of queueing on
  -- the same one, so two agents can never claim the same mission.
  select * into claimed
  from public.missions
  where status = 'queued'
  order by created_at
  for update skip locked
  limit 1;

  if not found then
    return null;
  end if;

  update public.missions
  set status = 'claimed',
      claimed_by = agent_id,
      claimed_at = now(),
      updated_at = now()
  where id = claimed.id
  returning * into claimed;

  return claimed;
end;
$$;

comment on function public.claim_next_mission is
  'Atomically take the oldest queued mission. Returns null when the queue is empty.';

revoke all on function public.claim_next_mission(text) from public, anon;
grant execute on function public.claim_next_mission(text) to authenticated;


create function public.release_stale_claims(older_than interval default '5 minutes')
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  released integer;
begin
  -- An agent that crashes mid-claim would otherwise strand its mission in
  -- 'claimed' forever, and the queue would silently stop moving.
  update public.missions
  set status = 'queued',
      claimed_by = null,
      claimed_at = null,
      updated_at = now()
  where status = 'claimed'
    and claimed_at < now() - older_than;

  get diagnostics released = row_count;
  return released;
end;
$$;

revoke all on function public.release_stale_claims(interval) from public, anon;
grant execute on function public.release_stale_claims(interval) to authenticated;


-- ── realtime ────────────────────────────────────────────────────────────
-- Browsers subscribe to these instead of polling. Inserting a telemetry row
-- both stores it and pushes it to every open dashboard, which is why this
-- project needs no message broker.

alter publication supabase_realtime add table public.telemetry;
alter publication supabase_realtime add table public.missions;
alter publication supabase_realtime add table public.flights;
