-- Public bucket for the desktop installers.
--
-- Public because the /setup page is: a visitor downloads the app before they
-- have an account, and there is nothing secret in an installer.
--
-- Public means *read* only. There are deliberately no storage policies here,
-- so neither anon nor authenticated can write, overwrite or delete an object.
-- The only writer is CI, using the service role, which bypasses RLS. Letting a
-- signed-in user replace the installer would let them ship arbitrary code to
-- every operator who downloads it.
--
-- Object paths are stable (`latest/CropWatcher-macos.dmg`) so the download
-- buttons never need a redeploy when a release is cut.
--
-- Idempotent: safe to re-run.

insert into storage.buckets (id, name, public)
values ('installers', 'installers', true)
on conflict (id) do update set public = excluded.public;
