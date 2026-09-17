-- A page per person: /team/<slug>.
--
-- 0007 gave each member a name, role, bio and photo — enough for a card. This
-- adds what a page needs: where it lives (slug), what they are doing now, what
-- they do outside the project, their own photos, and their links.
--
-- The three lists are jsonb, not three more tables:
--   * they are only ever read as a whole person, never queried across people
--   * the admin edits them as one form, saved in one write
--   * they carry no foreign keys
-- `photos` holds URLs in the existing portfolio-images bucket (0007). No new
-- bucket: the images are public either way, and one upload path is one set of
-- storage policies to get right.
--
-- Shape, enforced in the app (lib/team-profile.ts) rather than by a check
-- constraint, so a malformed row degrades to "no hobbies" instead of blocking
-- a save:
--   hobbies  [{ "title": text, "body": text, "image_url": text|null }]
--   links    [{ "label": text, "url": text }]
--   photos   [{ "url": text, "caption": text }]
--
-- The slug is unique and NOT derived at render time: two people called Sam
-- would collide, and renaming someone would silently move their page.
--
-- RLS is unchanged — 0007's "anyone reads the team" covers every column, and
-- only operators write. Idempotent: safe to re-run.

alter table public.team_members
  add column if not exists slug         text,
  add column if not exists headline     text        not null default '',
  add column if not exists location     text        not null default '',
  add column if not exists about        text        not null default '',
  add column if not exists current_work text        not null default '',
  add column if not exists hobbies      jsonb       not null default '[]'::jsonb,
  add column if not exists links        jsonb       not null default '[]'::jsonb,
  add column if not exists photos       jsonb       not null default '[]'::jsonb;

comment on column public.team_members.slug is
  'The URL of this person''s page: /team/<slug>. Stable across renames.';
comment on column public.team_members.current_work is
  'What they are working on right now — the answer to "what are you up to".';

-- Backfill: a slug from the name for everyone who predates this migration,
-- with a numeric suffix if two names reduce to the same thing.
with slugged as (
  select
    id,
    nullif(regexp_replace(lower(trim(full_name)), '[^a-z0-9]+', '-', 'g'), '') as base,
    row_number() over (
      partition by nullif(regexp_replace(lower(trim(full_name)), '[^a-z0-9]+', '-', 'g'), '')
      order by display_order, created_at
    ) as n
  from public.team_members
  where slug is null or slug = ''
)
update public.team_members m
set slug = case when s.n = 1 then coalesce(s.base, 'member') else coalesce(s.base, 'member') || '-' || s.n end
from slugged s
where m.id = s.id;

-- Trim any leading/trailing dashes the regexp left behind ("Sam!" -> "sam-").
update public.team_members
set slug = trim(both '-' from slug)
where slug like '-%' or slug like '%-';

create unique index if not exists team_members_slug_key on public.team_members (slug);

notify pgrst, 'reload schema';
