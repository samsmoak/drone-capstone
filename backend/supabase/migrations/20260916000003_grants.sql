-- Table privileges.
--
-- RLS and GRANT are two separate gates and BOTH must pass. Enabling RLS with
-- careful policies does nothing if the role has no table privilege: Postgres
-- refuses at the GRANT layer first, the policies never evaluate, and the app
-- looks broken for legitimate users while appearing "secure" in a test that
-- only ever checks that something was denied.
--
-- That is exactly what happened here. Before this migration `authenticated`
-- held only REFERENCES, TRIGGER and TRUNCATE, so an operator could not read
-- their own missions, and every "access denied" test passed for the wrong
-- reason.
--
-- The split of responsibility:
--   GRANT decides which *operations* a role may attempt.
--   RLS decides which *rows* it may touch.

-- ── anon: nothing ───────────────────────────────────────────────────────
-- Deliberately stricter than Supabase's default. There is no public surface
-- here: every page requires a session, and this app commands a real drone.

revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;
revoke all on all functions in schema public from anon;


-- ── authenticated: may attempt DML; RLS decides the rows ────────────────

grant select on
  public.profiles,
  public.drones,
  public.zones,
  public.flights,
  public.telemetry,
  public.missions,
  public.predictions
to authenticated;

grant insert on
  public.flights,
  public.telemetry,
  public.missions,
  public.predictions,
  public.zones
to authenticated;

grant update on
  public.profiles,
  public.flights,
  public.missions,
  public.zones
to authenticated;

-- Telemetry is an append-only record of what the sensors reported: no update,
-- no delete, so a flight log cannot be edited after the fact.

grant delete on public.zones to authenticated;

-- telemetry.id is a bigserial, so inserts need the sequence too. Missing this
-- fails only on INSERT, which a read-only test would never catch.
grant usage, select on all sequences in schema public to authenticated;


-- ── defaults for tables added later ─────────────────────────────────────
-- Without this, the next migration's table silently arrives with no grants
-- and reproduces the bug above.

alter default privileges in schema public
  grant select, insert, update on tables to authenticated;

alter default privileges in schema public
  grant usage, select on sequences to authenticated;
