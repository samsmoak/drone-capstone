-- ── notifications: a finding worth a look, kept until it is read ─────────
--
-- The owner, 2026-10-09: notifications must be PERSISTENT in the web app. So
-- they are rows, one per operator per finding, kept until that operator reads
-- them — whoever was offline sees them at their next sign-in. Realtime only
-- makes a new one arrive at once; the table is the record.
--
-- Made by the DATABASE, never by a client: a trigger on pipeline_findings
-- inserts one row for every operator when a WARNING or CRITICAL finding is
-- INSERTED. An upsert that updates an existing finding (a flight processed
-- again) fires no insert trigger, and (user_id, finding_id) is unique, so a
-- re-upload never notifies twice. A finding a re-process retracts takes its
-- notifications with it (on delete cascade).
--
-- Each operator reads and marks only their own: select and update by
-- user_id = auth.uid(), and the update grant is on read_at ALONE — nobody can
-- rewrite a notification's words or move it to someone else. No insert or
-- delete for any client role.

create table if not exists public.notifications (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles (id) on delete cascade,
  finding_id  uuid not null references public.pipeline_findings (id) on delete cascade,
  flight_id   uuid references public.flights (id) on delete cascade,
  session_id  uuid references public.sessions (id) on delete set null,
  severity    text not null check (severity in ('warning', 'critical')),
  title       text not null,
  body        text not null,
  created_at  timestamptz not null default now(),
  read_at     timestamptz,
  unique (user_id, finding_id)
);

create index if not exists notifications_inbox_idx
  on public.notifications (user_id, created_at desc);
create index if not exists notifications_unread_idx
  on public.notifications (user_id) where read_at is null;

alter table public.notifications enable row level security;

drop policy if exists "read your own notifications" on public.notifications;
create policy "read your own notifications"
  on public.notifications for select to authenticated using (user_id = auth.uid());

drop policy if exists "mark your own notifications read" on public.notifications;
create policy "mark your own notifications read"
  on public.notifications for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

revoke all on public.notifications from anon, authenticated;
grant select on public.notifications to authenticated;
grant update (read_at) on public.notifications to authenticated;


create or replace function public.notify_operators_of_finding()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.severity not in ('warning', 'critical') then
    return new;
  end if;
  insert into public.notifications (user_id, finding_id, flight_id, session_id, severity,
                                    title, body)
  select p.id, new.id, new.flight_id, new.session_id, new.severity, new.title, new.sentence
    from public.profiles p
   where p.role = 'operator'
  on conflict (user_id, finding_id) do nothing;
  return new;
end;
$$;

revoke all on function public.notify_operators_of_finding() from public, anon, authenticated;

drop trigger if exists pipeline_findings_notify on public.pipeline_findings;
create trigger pipeline_findings_notify
  after insert on public.pipeline_findings
  for each row execute function public.notify_operators_of_finding();

-- Realtime: a new notification reaches an open page at once. Row-level
-- security decides what each socket receives — only its own user's rows.
do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public'
                   and tablename = 'notifications') then
    alter publication supabase_realtime add table public.notifications;
  end if;
end;
$$;
