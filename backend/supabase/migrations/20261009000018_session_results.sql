-- ── a session's own pipeline result ─────────────────────────────────────
--
-- `cropwatcher process --session` (the owner, 2026-10-09: "as long as a
-- session is started we process whatever data comes, not only data in
-- flight") writes results/sessions/<session>/result.json on the laptop first
-- (CLAUDE.md invariant 6): the session's one-a-second samples around its
-- flights, cleaned, the frames taken outside its flights enhanced, and the
-- stretches on the ground judged (stages/classify/ground.py). The agent's
-- outbox uploads it here (sync: Kind.SESSION_RESULTS):
--
--   pipeline_session_results  ONE ROW PER SESSION — the same shape as a
--                             flight's pipeline_results row; re-processing
--                             replaces it.
--   pipeline_findings         gains SESSION findings: scope 'session', no
--                             flight, the session's id. A flight's findings
--                             keep scope 'flight' (the default) and are
--                             untouched.
--
-- Same access as a flight's result (20261009000016): every signed-in user
-- reads, operators write, anon nothing; explicit grants. Notifications
-- (20261009000017) already allow a finding with no flight.

create table if not exists public.pipeline_session_results (
  session_id        uuid primary key references public.sessions (id) on delete cascade,
  pipeline_version  text not null,
  stages            jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null,               -- when the pipeline ran
  temp_unit         text not null default 'C' check (temp_unit in ('C', 'F')),
  points            jsonb not null default '[]'::jsonb,
  findings_count    integer not null default 0,
  worst_severity    text check (worst_severity in ('info', 'warning', 'critical')),
  flags             jsonb not null default '[]'::jsonb, -- [index, column, kind, reason]
  tracks            jsonb not null default '[]'::jsonb,
  segments          jsonb not null default '[]'::jsonb,
  frames            jsonb not null default '[]'::jsonb,
  failures          jsonb not null default '[]'::jsonb,
  summary           jsonb not null default '{}'::jsonb,
  uploaded_by       uuid default auth.uid() references public.profiles (id),
  uploaded_at       timestamptz not null default now()
);

-- A session's finding has no flight. Every finding still belongs to one: a
-- flight (scope 'flight') or a session (scope 'session').
alter table public.pipeline_findings alter column flight_id drop not null;
alter table public.pipeline_findings
  add column if not exists scope text not null default 'flight';
alter table public.pipeline_findings drop constraint if exists pipeline_findings_scope_check;
alter table public.pipeline_findings
  add constraint pipeline_findings_scope_check check (
    (scope = 'flight' and flight_id is not null)
    or (scope = 'session' and session_id is not null));

-- pipeline_findings.session_id is "on delete set null" (a flight's findings
-- outlive their session's row). A SESSION's findings cannot — they would
-- belong to nothing — so they go with their session.
create or replace function public.delete_session_findings()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  delete from public.pipeline_findings where scope = 'session' and session_id = old.id;
  return old;
end;
$$;

revoke all on function public.delete_session_findings() from public, anon, authenticated;

drop trigger if exists sessions_delete_session_findings on public.sessions;
create trigger sessions_delete_session_findings
  before delete on public.sessions
  for each row execute function public.delete_session_findings();

alter table public.pipeline_session_results enable row level security;

drop policy if exists "signed-in read session results" on public.pipeline_session_results;
create policy "signed-in read session results"
  on public.pipeline_session_results for select to authenticated using (true);
drop policy if exists "operators write session results" on public.pipeline_session_results;
create policy "operators write session results"
  on public.pipeline_session_results for insert to authenticated
  with check (public.is_operator());
drop policy if exists "operators replace session results" on public.pipeline_session_results;
create policy "operators replace session results"
  on public.pipeline_session_results for update to authenticated
  using (public.is_operator()) with check (public.is_operator());

grant select, insert, update on public.pipeline_session_results to authenticated;
revoke all on public.pipeline_session_results from anon;
