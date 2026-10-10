-- ── session_samples: the grants its policies need ────────────────────────
--
-- 20261006000013 created session_samples with row-level security policies
-- and NO grant. This project revokes the hosted platform's default privileges
-- (20260916000004), so a table without an explicit grant is refused to every
-- role whatever its policies say — "a policy without a grant is a 403"
-- (docs/features/supabase/rls-and-grants.txt). The Sessions page's read and
-- the agent's upload would both have failed.
--
-- Exactly what telemetry has: read and append for signed-in users, the
-- policies deciding which rows; no update or delete — the record is
-- append-only. Nothing for anon.

grant select, insert on public.session_samples to authenticated;
