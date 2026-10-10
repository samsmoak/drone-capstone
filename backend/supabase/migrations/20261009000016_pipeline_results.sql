-- ── the data pipeline's results, on the web ──────────────────────────────
--
-- `cropwatcher process` writes results/<flight>/result.json on the laptop
-- first (CLAUDE.md invariant 6); the agent's outbox then uploads it here
-- (sync: Kind.RESULTS). Two tables:
--
--   pipeline_results   ONE ROW PER FLIGHT: the whole result — verdicts, the
--                      cleaner's flags, the tracks (observed and expected per
--                      reading), the blocks, every frame's enhanced copy and
--                      quality. Re-processing a flight REPLACES its row.
--   pipeline_findings  ONE ROW PER FINDING, for the pages that list them and
--                      for notifications (20261009000017). The id is made on
--                      the laptop from the flight and the stretch, so the same
--                      stretch keeps its id when the flight is processed again
--                      (an upsert, not a duplicate); findings a re-process no
--                      longer makes are deleted by the agent.
--
-- Read by every signed-in user, like flights and telemetry. Written by
-- operators only. anon: nothing. Explicit grants — "a policy without a grant
-- is a 403" (docs/features/supabase/rls-and-grants.txt).

create table if not exists public.pipeline_results (
  flight_id         uuid primary key references public.flights (id) on delete cascade,
  session_id        uuid references public.sessions (id) on delete set null,
  pipeline_version  text not null,
  stages            jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null,               -- when the pipeline ran
  temp_unit         text not null default 'C' check (temp_unit in ('C', 'F')),
  points            jsonb not null default '[]'::jsonb, -- a verdict per inspection point
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

create index if not exists pipeline_results_session_idx on public.pipeline_results (session_id);

create table if not exists public.pipeline_findings (
  id               uuid primary key,                    -- made on the laptop (uuid5)
  flight_id        uuid not null references public.flights (id) on delete cascade,
  session_id       uuid references public.sessions (id) on delete set null,
  signal           text not null check (signal in ('temperature', 'pressure')),
  severity         text not null check (severity in ('info', 'warning', 'critical')),
  title            text not null,
  sentence         text not null,
  start_index      integer not null,
  end_index        integer not null,
  t_start_s        double precision not null,
  t_end_s          double precision not null,
  unit             text not null,
  observed         double precision,
  expected         double precision,
  delta            double precision,
  z                double precision,
  point_ids        text[] not null default '{}',
  x_m              double precision,
  y_m              double precision,
  z_m              double precision,
  evidence_frames  integer[] not null default '{}',
  image_support    text not null check (image_support in ('supports', 'contradicts', 'cannot_tell')),
  image_note       text not null default '',
  pipeline_version text not null,
  created_at       timestamptz not null default now()
);

create index if not exists pipeline_findings_flight_idx on public.pipeline_findings (flight_id);
create index if not exists pipeline_findings_session_idx
  on public.pipeline_findings (session_id, severity);

alter table public.pipeline_results enable row level security;
alter table public.pipeline_findings enable row level security;

drop policy if exists "signed-in read pipeline results" on public.pipeline_results;
create policy "signed-in read pipeline results"
  on public.pipeline_results for select to authenticated using (true);
drop policy if exists "operators write pipeline results" on public.pipeline_results;
create policy "operators write pipeline results"
  on public.pipeline_results for insert to authenticated with check (public.is_operator());
drop policy if exists "operators replace pipeline results" on public.pipeline_results;
create policy "operators replace pipeline results"
  on public.pipeline_results for update to authenticated
  using (public.is_operator()) with check (public.is_operator());

drop policy if exists "signed-in read pipeline findings" on public.pipeline_findings;
create policy "signed-in read pipeline findings"
  on public.pipeline_findings for select to authenticated using (true);
drop policy if exists "operators write pipeline findings" on public.pipeline_findings;
create policy "operators write pipeline findings"
  on public.pipeline_findings for insert to authenticated with check (public.is_operator());
drop policy if exists "operators replace pipeline findings" on public.pipeline_findings;
create policy "operators replace pipeline findings"
  on public.pipeline_findings for update to authenticated
  using (public.is_operator()) with check (public.is_operator());
-- A re-process that no longer makes a finding deletes it.
drop policy if exists "operators retract pipeline findings" on public.pipeline_findings;
create policy "operators retract pipeline findings"
  on public.pipeline_findings for delete to authenticated using (public.is_operator());

grant select, insert, update on public.pipeline_results to authenticated;
grant select, insert, update, delete on public.pipeline_findings to authenticated;
revoke all on public.pipeline_results from anon;
revoke all on public.pipeline_findings from anon;
