-- ── session_samples: the whole session's vitals, flying or not ───────────
--
-- A flight's telemetry (10 Hz) is recorded only between its motors starting
-- and landing. The session itself keeps one sample a second from Start
-- session to End session (agent history.py, sessions/<id>/samples.csv) —
-- battery, temperature, pressure, positioning — and until now that never left
-- the laptop, so a session with no flight showed nothing on the web. The web
-- app's Sessions tab reads this (2026-10-06, Samuel).
--
-- Column names mirror public.telemetry wherever they mean the same, so the
-- flight page's charts, path and raw-readings table read both. `values` keeps
-- every stream variable of the sample, so nothing recorded is dropped.
--
-- `positioned`: the drone trusted its x-y at that sample (agent
-- flight_guard.position_trusted). A path is drawn only from positioned rows:
-- an unmeasured base station gives a drifting estimate, which is not a place.

create table if not exists public.session_samples (
  session_id            uuid not null references public.sessions (id) on delete cascade,
  seq                   integer not null,          -- the row in samples.csv, from 1
  recorded_at           timestamptz not null,
  mode                  text,
  height_m              double precision,          -- above the takeoff floor, when known
  x_m                   double precision,
  y_m                   double precision,
  z_m                   double precision,
  positioned            boolean,
  battery_v             double precision,
  raw_temp              double precision,          -- the barometer's own sensor, °C
  station_pressure_hpa  double precision,
  roll_deg              double precision,
  pitch_deg             double precision,
  yaw_deg               double precision,
  thrust                double precision,
  lighthouse_received   integer,                   -- bsReceive bit field
  "values"              jsonb not null default '{}'::jsonb,
  primary key (session_id, seq)                    -- a re-sent batch changes nothing
);

create index if not exists session_samples_time_idx
  on public.session_samples (session_id, recorded_at);

alter table public.session_samples enable row level security;

drop policy if exists "signed-in read session samples" on public.session_samples;
create policy "signed-in read session samples"
  on public.session_samples for select to authenticated using (true);

-- An operator records samples only for a session that is theirs.
drop policy if exists "operators write their own session samples" on public.session_samples;
create policy "operators write their own session samples"
  on public.session_samples for insert to authenticated
  with check (
    public.is_operator()
    and exists (select 1 from public.sessions s
                where s.id = session_id and s.operator_id = auth.uid())
  );

-- Append-only, like telemetry: no update or delete policy.
