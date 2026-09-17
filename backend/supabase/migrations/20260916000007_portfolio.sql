-- The public portfolio: projects, the team, and who worked on what.
--
-- Ported from ../doctor-portfolio (projects + BlockNote write-ups + admin CMS),
-- adapted to this project:
--   * one site, so no `sites` table and no site_id on every row
--   * the admin is any operator (public.is_operator()), not a Google allow-list
--   * people are their own table, shown beside each project, instead of one
--     owner profile
--
-- Anyone may read the team and PUBLISHED projects. Only operators write.
-- Idempotent: safe to re-run.

-- ── team ────────────────────────────────────────────────────────────────

create table if not exists public.team_members (
  id            uuid primary key default gen_random_uuid(),
  full_name     text not null,
  role          text not null default '',
  bio           text not null default '',
  avatar_url    text,
  website_url   text,
  email         text,
  display_order integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.team_members is
  'People shown on /team and beside the projects they worked on. Public.';

-- ── projects ────────────────────────────────────────────────────────────

create table if not exists public.projects (
  id              uuid primary key default gen_random_uuid(),
  slug            text not null unique,
  title           text not null default '',
  subtitle        text not null default '',
  summary         text not null default '',
  cover_image_url text,
  category        text not null default 'engineering',
  date_label      text not null default '',
  location        text not null default '',
  status          text not null default 'draft' check (status in ('draft', 'published')),
  display_order   integer not null default 0,
  -- A BlockNote document. Rendered to static HTML on the public page.
  content         jsonb not null default '[]'::jsonb,
  published_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists projects_published_order
  on public.projects (status, display_order);

-- ── who worked on what ──────────────────────────────────────────────────

create table if not exists public.project_members (
  project_id    uuid not null references public.projects(id) on delete cascade,
  member_id     uuid not null references public.team_members(id) on delete cascade,
  display_order integer not null default 0,
  primary key (project_id, member_id)
);

-- ── row-level security ──────────────────────────────────────────────────

alter table public.team_members    enable row level security;
alter table public.projects        enable row level security;
alter table public.project_members enable row level security;

drop policy if exists "anyone reads the team" on public.team_members;
create policy "anyone reads the team"
  on public.team_members for select to anon, authenticated using (true);

drop policy if exists "operators manage the team" on public.team_members;
create policy "operators manage the team"
  on public.team_members for all to authenticated
  using (public.is_operator()) with check (public.is_operator());

-- A draft is visible to operators only: the public never sees a half-written page.
drop policy if exists "anyone reads published projects" on public.projects;
create policy "anyone reads published projects"
  on public.projects for select to anon, authenticated
  using (status = 'published' or public.is_operator());

drop policy if exists "operators manage projects" on public.projects;
create policy "operators manage projects"
  on public.projects for all to authenticated
  using (public.is_operator()) with check (public.is_operator());

drop policy if exists "anyone reads published project teams" on public.project_members;
create policy "anyone reads published project teams"
  on public.project_members for select to anon, authenticated
  using (
    public.is_operator() or exists (
      select 1 from public.projects p
      where p.id = project_id and p.status = 'published'
    )
  );

drop policy if exists "operators manage project teams" on public.project_members;
create policy "operators manage project teams"
  on public.project_members for all to authenticated
  using (public.is_operator()) with check (public.is_operator());

-- ── grants ──────────────────────────────────────────────────────────────
-- 0004 revoked the platform defaults, so a policy with no grant is a 403.
-- Both halves, together.

grant select on public.team_members, public.projects, public.project_members to anon;
grant select, insert, update, delete
  on public.team_members, public.projects, public.project_members to authenticated;

-- The anon role needs to call is_operator() for the select policies above.
grant execute on function public.is_operator() to anon;

-- ── images ──────────────────────────────────────────────────────────────
-- Public read (project covers and team photos are on public pages), operator
-- write. Nothing private may ever be uploaded here: a public URL cannot be
-- revoked.

insert into storage.buckets (id, name, public)
values ('portfolio-images', 'portfolio-images', true)
on conflict (id) do update set public = excluded.public;

drop policy if exists "operators upload portfolio images" on storage.objects;
create policy "operators upload portfolio images"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'portfolio-images' and public.is_operator());

drop policy if exists "operators replace portfolio images" on storage.objects;
create policy "operators replace portfolio images"
  on storage.objects for update to authenticated
  using (bucket_id = 'portfolio-images' and public.is_operator());

drop policy if exists "operators delete portfolio images" on storage.objects;
create policy "operators delete portfolio images"
  on storage.objects for delete to authenticated
  using (bucket_id = 'portfolio-images' and public.is_operator());
