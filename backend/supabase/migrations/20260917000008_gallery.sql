-- The public gallery: albums of photos and videos.
--
-- Albums are grouped like projects — a grid of album cards, each opening to its
-- photos and videos. Categories are free text (hardware, team, flights, …) so a
-- new kind of album needs no migration.
--
-- A video item is a YouTube link (played through the privacy-enhanced embed);
-- an image item is a URL in the portfolio-images bucket (migration 0007).
-- width/height are stored so the page can lay photos out at their real aspect
-- ratio without loading them first.
--
-- Anyone reads published albums and their items; only operators write.
-- Idempotent: safe to re-run.

create table if not exists public.gallery_albums (
  id              uuid primary key default gen_random_uuid(),
  slug            text not null unique,
  title           text not null default '',
  summary         text not null default '',
  category        text not null default '',
  cover_image_url text,
  date_label      text not null default '',
  status          text not null default 'draft' check (status in ('draft', 'published')),
  display_order   integer not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.gallery_items (
  id            uuid primary key default gen_random_uuid(),
  album_id      uuid not null references public.gallery_albums(id) on delete cascade,
  kind          text not null check (kind in ('image', 'video')),
  url           text not null,
  caption       text not null default '',
  credit        text not null default '',
  width         integer,
  height        integer,
  display_order integer not null default 0,
  created_at    timestamptz not null default now()
);

create index if not exists gallery_items_album_order
  on public.gallery_items (album_id, display_order);

alter table public.gallery_albums enable row level security;
alter table public.gallery_items  enable row level security;

drop policy if exists "anyone reads published albums" on public.gallery_albums;
create policy "anyone reads published albums"
  on public.gallery_albums for select to anon, authenticated
  using (status = 'published' or public.is_operator());

drop policy if exists "operators manage albums" on public.gallery_albums;
create policy "operators manage albums"
  on public.gallery_albums for all to authenticated
  using (public.is_operator()) with check (public.is_operator());

drop policy if exists "anyone reads published album items" on public.gallery_items;
create policy "anyone reads published album items"
  on public.gallery_items for select to anon, authenticated
  using (
    public.is_operator() or exists (
      select 1 from public.gallery_albums a
      where a.id = album_id and a.status = 'published'
    )
  );

drop policy if exists "operators manage album items" on public.gallery_items;
create policy "operators manage album items"
  on public.gallery_items for all to authenticated
  using (public.is_operator()) with check (public.is_operator());

-- 0004 revoked the platform defaults: a policy with no grant is a 403.
grant select on public.gallery_albums, public.gallery_items to anon;
grant select, insert, update, delete on public.gallery_albums, public.gallery_items to authenticated;

notify pgrst, 'reload schema';
