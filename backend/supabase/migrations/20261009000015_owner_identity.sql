-- ── who ran it: the owner's name and email on every session and flight ──
--
-- The agent records who ran a session (sessions.operator_id) and a flight
-- (flights.created_by), but profiles are "read own profile" only
-- (20260916000002), so the web could show the name of nobody but the viewer:
-- every other operator's session read "—" (owner, 2026-10-09: "make sure that
-- sessions, flights, things that were run are tied to an owner").
--
-- Opening profiles to every signed-in user would hand each of them every
-- account's email. Instead the two records carry their own owner's name and
-- email, the same way audit_events carries actor_email: stamped HERE, by the
-- database, from profiles — never taken from what a client sends. The trigger
-- runs on every insert and update, so a client cannot set or edit them.
--
-- A flight with no created_by takes its session's operator. A name changed
-- in profiles later is not rewritten into old records: they say who ran
-- them, as they were then.

alter table public.sessions
  add column if not exists operator_email text,
  add column if not exists operator_name  text;

alter table public.flights
  add column if not exists operator_email text,
  add column if not exists operator_name  text;


create or replace function public.stamp_session_owner()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  select p.email, p.full_name
    into new.operator_email, new.operator_name
    from public.profiles p
   where p.id = new.operator_id;
  if not found then
    new.operator_email := null;
    new.operator_name := null;
  end if;
  return new;
end;
$$;

create or replace function public.stamp_flight_owner()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  owner uuid := new.created_by;
begin
  if owner is null and new.session_id is not null then
    select s.operator_id into owner from public.sessions s where s.id = new.session_id;
  end if;
  select p.email, p.full_name
    into new.operator_email, new.operator_name
    from public.profiles p
   where p.id = owner;
  if not found then
    new.operator_email := null;
    new.operator_name := null;
  end if;
  return new;
end;
$$;

-- Trigger functions only: no role calls them directly.
revoke all on function public.stamp_session_owner() from public, anon, authenticated;
revoke all on function public.stamp_flight_owner() from public, anon, authenticated;

drop trigger if exists sessions_stamp_owner on public.sessions;
create trigger sessions_stamp_owner
  before insert or update on public.sessions
  for each row execute function public.stamp_session_owner();

drop trigger if exists flights_stamp_owner on public.flights;
create trigger flights_stamp_owner
  before insert or update on public.flights
  for each row execute function public.stamp_flight_owner();


-- ── backfill every record already uploaded ──────────────────────────────

update public.sessions s
   set operator_email = p.email, operator_name = p.full_name
  from public.profiles p
 where p.id = s.operator_id;

update public.flights f
   set operator_email = p.email, operator_name = p.full_name
  from public.profiles p
 where p.id = coalesce(f.created_by,
                       (select s.operator_id from public.sessions s where s.id = f.session_id));

-- No new grants: the columns ride on the existing select on sessions and
-- flights (signed-in read). anon still has nothing.
