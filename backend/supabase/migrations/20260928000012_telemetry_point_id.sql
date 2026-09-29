-- ── telemetry: which inspection point a reading was taken at ─────────────
--
-- The agent stamps point_id into every telemetry row while the mission
-- controller is HOLDING at an inspection point, and leaves it empty otherwise
-- (planning story 3.5: "every collected reading ... tagged with ... associated
-- inspection point ID"). The data pipeline groups readings by it.
--
-- Mirrors cropwatcher.telemetry.row.TelemetryRow.point_id. Until this is
-- applied the agent omits the key from any batch that carries no point id
-- (sync/cloud.py without_empty_point_id), so flights with no mission upload as
-- before; a mission flight's batch is retried without the column, and the tag
-- survives only in the laptop's CSV. Apply this before flying missions.
--
-- Text, not uuid: point ids are the mission's own short ids ("P1"), unique
-- within a mission, not across the database. No new policy: the existing
-- telemetry row-level security covers the new column.

alter table public.telemetry add column if not exists point_id text;

create index if not exists telemetry_flight_point_idx
  on public.telemetry (flight_id, point_id)
  where point_id is not null;
