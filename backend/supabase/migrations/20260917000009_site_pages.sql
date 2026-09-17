-- Editable wording for every public page.
--
-- One row per page, keyed by name (home, setup, hardware, projects, team,
-- gallery, site). `content` is JSON shaped by the page's field spec in
-- web/lib/site-content.ts, which also holds the default wording: a page with no
-- row renders its defaults, so a page can never blank for want of a row, and
-- "reset to default" is deleting the row.
--
-- Anyone reads; only operators write. Idempotent: safe to re-run.

create table if not exists public.site_pages (
  key        text primary key,
  content    jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id) on delete set null
);

alter table public.site_pages enable row level security;

drop policy if exists "anyone reads site pages" on public.site_pages;
create policy "anyone reads site pages"
  on public.site_pages for select to anon, authenticated using (true);

drop policy if exists "operators edit site pages" on public.site_pages;
create policy "operators edit site pages"
  on public.site_pages for all to authenticated
  using (public.is_operator()) with check (public.is_operator());

grant select on public.site_pages to anon;
grant select, insert, update, delete on public.site_pages to authenticated;

notify pgrst, 'reload schema';
