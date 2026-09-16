-- Make table privileges deterministic.
--
-- Hosted Supabase projects ship default privileges that grant ALL on every
-- table in `public` to anon, authenticated and service_role. A local stack
-- does not. So the same migrations produce a *more permissive* hosted database
-- than the one they were tested against — which is the worst direction for a
-- difference to run in.
--
-- Concretely, this migration was written because verification on the hosted
-- project found `authenticated` holding DELETE on `telemetry`, which migration
-- 0003 never granted. RLS still blocked it (there is no delete policy), so it
-- was not exploitable — but append-only then rested on one gate instead of two.
--
-- Rather than assume either platform's defaults, revoke everything and re-grant
-- exactly what the app needs. Idempotent: safe to re-run anywhere.

-- ── start from nothing ──────────────────────────────────────────────────

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

-- Stop the platform defaults re-granting ALL on the next table created.
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;


-- ── anon: nothing at all ────────────────────────────────────────────────
-- Every page requires a session and this app commands a real drone, so there
-- is no anonymous surface to support.


-- ── authenticated: exactly what each table needs ────────────────────────

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

-- Deletion is limited to zones, which are configuration. Flights and their
-- telemetry are the experimental record: removing one is an admin action
-- through the dashboard, not something the app can do.
grant delete on public.zones to authenticated;

-- telemetry.id is a bigserial, so inserts need the sequence.
grant usage, select on all sequences in schema public to authenticated;


-- ── defaults for tables added later ─────────────────────────────────────

alter default privileges in schema public
  grant select, insert, update on tables to authenticated;

alter default privileges in schema public
  grant usage, select on sequences to authenticated;
