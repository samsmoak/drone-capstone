-- CropWatcher initial schema.
--
-- Auth note: both email/password and Google OAuth sign-ins land in the same
-- auth.users table and produce the same auth.uid(), so every policy below works
-- for either. Email/password needs no external configuration, which is why it
-- is the one to develop against; Google can be switched on later without a
-- schema change.
--
-- RLS is deny-by-default on every table. This app is publicly reachable and it
-- commands a physical drone: an unauthenticated insert into `missions` would
-- put a real aircraft in the air.

-- ── profiles ────────────────────────────────────────────────────────────
-- One row per signed-in person, mirroring auth.users so the app can read a
-- display name without touching the auth schema.

create table public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null,
  full_name   text,
  -- 'operator' may queue and fly missions; 'viewer' may only read.
  role        text not null default 'operator'
              check (role in ('operator', 'viewer')),
  created_at  timestamptz not null default now()
);

comment on table public.profiles is
  'App-level user record. Populated by a trigger on auth.users signup.';

-- New signups get a profile automatically, whichever provider they used.
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.email)
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();


-- ── drones ──────────────────────────────────────────────────────────────

create table public.drones (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  uri         text not null default 'radio://0/80/2M',
  notes       text,
  created_at  timestamptz not null default now()
);


-- ── zones ───────────────────────────────────────────────────────────────
-- The greenhouse grid. Bounds are metres relative to the takeoff point, the
-- same frame every flight coordinate uses.

create table public.zones (
  id          uuid primary key default gen_random_uuid(),
  label       text not null unique,
  x_min       double precision not null,
  x_max       double precision not null,
  y_min       double precision not null,
  y_max       double precision not null,
  created_at  timestamptz not null default now(),
  constraint zone_bounds_ordered check (x_min < x_max and y_min < y_max)
);


-- ── flights ─────────────────────────────────────────────────────────────

create type public.flight_status as enum ('running', 'completed', 'aborted', 'failed');

create table public.flights (
  id            uuid primary key default gen_random_uuid(),
  drone_id      uuid references public.drones (id) on delete set null,
  created_by    uuid references public.profiles (id) on delete set null,
  status        public.flight_status not null default 'running',
  -- The unit every temperature column in this flight's telemetry is stored in.
  -- Recorded per flight because the operator chooses it at launch, and a column
  -- of temperatures with no unit quietly invalidates the dataset.
  temp_unit     text not null default 'C' check (temp_unit in ('C', 'F')),
  ambient_start double precision,
  -- Lighthouse z of the floor at takeoff. Telemetry z is relative to this, so
  -- without it the stored altitudes cannot be mapped back to the room.
  ground_z_m    double precision,
  csv_path      text,
  error         text,
  started_at    timestamptz not null default now(),
  ended_at      timestamptz
);

create index flights_started_at_idx on public.flights (started_at desc);


-- ── telemetry ───────────────────────────────────────────────────────────
-- Mirrors cropwatcher.telemetry.row.TelemetryRow exactly. If you add a column
-- there, add it here in the same commit or the upload silently drops it.

create table public.telemetry (
  id                      bigserial primary key,
  flight_id               uuid not null references public.flights (id) on delete cascade,
  index                   integer not null,
  recorded_at             timestamptz not null,

  mode                    text,
  thermal_state           text,
  event                   text,

  temp_unit               text not null,
  raw_temp                double precision,
  corrected_temp          double precision,
  expected_raw            double precision,
  deviation               double precision,
  thermal_offset          double precision,
  ambient_est             double precision,
  roc_per_s               double precision,

  station_pressure_hpa    double precision,
  sea_level_pressure_hpa  double precision,
  air_density_kg_m3       double precision,
  pressure_altitude_m     double precision,

  battery_v               double precision,
  thrust                  integer,

  -- Metres, relative to the flight's ground_z_m. NOT raw lighthouse z.
  x_m                     double precision,
  y_m                     double precision,
  z_m                     double precision,

  unique (flight_id, index)
);

-- The dominant read is "this flight, in order", for charts and path replay.
create index telemetry_flight_time_idx
  on public.telemetry (flight_id, recorded_at);


-- ── missions ────────────────────────────────────────────────────────────
-- The queue. The agent polls this; nothing pushes to the agent, because the
-- laptop sits behind a router with no public address.

create type public.mission_status as enum
  ('queued', 'claimed', 'running', 'done', 'failed', 'cancelled');

create table public.missions (
  id           uuid primary key default gen_random_uuid(),
  created_by   uuid references public.profiles (id) on delete set null,
  name         text not null default 'mission',
  type         text not null check (type in ('hover', 'lawnmower', 'waypoint')),
  -- The full plan, exactly as Mission.to_dict() produces it. Stored whole so
  -- the agent flies what was reviewed, not a re-derivation of it.
  plan         jsonb not null,
  status       public.mission_status not null default 'queued',
  claimed_by   text,
  claimed_at   timestamptz,
  flight_id    uuid references public.flights (id) on delete set null,
  error        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index missions_queue_idx
  on public.missions (status, created_at)
  where status in ('queued', 'claimed');


-- ── predictions ─────────────────────────────────────────────────────────

create table public.predictions (
  id             uuid primary key default gen_random_uuid(),
  flight_id      uuid not null references public.flights (id) on delete cascade,
  zone_id        uuid references public.zones (id) on delete cascade,
  health_score   double precision,
  disease_risk   double precision,
  label          text,
  model          text not null default 'lnn',
  sample_count   integer,
  notes          text,
  created_at     timestamptz not null default now()
);

create index predictions_flight_idx on public.predictions (flight_id);
