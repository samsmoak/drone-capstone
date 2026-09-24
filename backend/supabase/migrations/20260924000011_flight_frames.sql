-- ── camera frame storage ────────────────────────────────────────────────
--
-- A session's recorded camera frames (backend/agent/cropwatcher/camera/
-- recording.py): about two a second, uploaded from the laptop after they are
-- written to disk, plus that session's frames.csv index.
--
--   flight-frames/<session_id>/frames/000001.png
--   flight-frames/<session_id>/frames.csv
--
-- Private, exactly like flight-logs: a frame is operator data. Operators may
-- upload and read; the index is replaced once at the session's end, so
-- operators may also update.

insert into storage.buckets (id, name, public)
values ('flight-frames', 'flight-frames', false)
on conflict (id) do update set public = excluded.public;

drop policy if exists "operators upload flight frames" on storage.objects;
create policy "operators upload flight frames"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'flight-frames' and public.is_operator());

drop policy if exists "operators read flight frames" on storage.objects;
create policy "operators read flight frames"
  on storage.objects for select to authenticated
  using (bucket_id = 'flight-frames' and public.is_operator());

-- The frames.csv index is uploaded with upsert at a session's end.
drop policy if exists "operators replace flight frames" on storage.objects;
create policy "operators replace flight frames"
  on storage.objects for update to authenticated
  using (bucket_id = 'flight-frames' and public.is_operator())
  with check (bucket_id = 'flight-frames' and public.is_operator());
