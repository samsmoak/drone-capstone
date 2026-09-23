-- Development seed.
--
-- Run against a LOCAL Supabase only (`supabase db reset`). It creates a
-- password user so you can sign in immediately without configuring Google
-- OAuth redirect URLs — that can be switched on later with no schema change.
--
--   email:    operator@cropwatcher.local
--   password: cropwatcher
--
-- Never run this against production: the password is public in this file.

-- ── a signed-in-able user ───────────────────────────────────────────────
-- Inserting into auth.users directly is only appropriate for local seeding.
-- In production, sign up through the app and the trigger creates the profile.

-- The token columns MUST be empty strings, not NULL. GoTrue scans them into
-- Go `string` values, and a NULL makes every sign-in fail with a 500 and
-- "converting NULL to string is unsupported" — which surfaces to the client as
-- "Database error querying schema" and looks nothing like a seeding problem.

insert into auth.users (
  instance_id, id, aud, role, email,
  encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data,
  created_at, updated_at,
  confirmation_token, recovery_token,
  email_change_token_new, email_change, email_change_token_current,
  phone_change, phone_change_token, reauthentication_token
)
values (
  '00000000-0000-0000-0000-000000000000',
  '11111111-1111-1111-1111-111111111111',
  'authenticated', 'authenticated', 'operator@cropwatcher.local',
  crypt('cropwatcher', gen_salt('bf')),
  now(),
  '{"provider":"email","providers":["email"]}',
  '{"full_name":"Demo Operator"}',
  now(), now(),
  '', '', '', '', '', '', '', ''
)
on conflict (id) do nothing;

insert into auth.identities (
  id, user_id, provider_id, identity_data, provider, created_at, updated_at
)
values (
  '11111111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  '11111111-1111-1111-1111-111111111111',
  '{"sub":"11111111-1111-1111-1111-111111111111","email":"operator@cropwatcher.local"}',
  'email', now(), now()
)
on conflict (provider, provider_id) do nothing;

-- The signup trigger normally creates this; seeded users bypass it.
insert into public.profiles (id, email, full_name, role)
values (
  '11111111-1111-1111-1111-111111111111',
  'operator@cropwatcher.local',
  'Demo Operator',
  'operator'
)
on conflict (id) do nothing;


-- ── the drone ───────────────────────────────────────────────────────────

insert into public.drones (id, name, uri, notes)
values (
  '22222222-2222-2222-2222-222222222222',
  'CropWatcher 1',
  'radio://0/80/2M',
  'Crazyflie 2.1 with Lighthouse deck and AI deck. Camera unused.'
)
on conflict (id) do nothing;


-- ── a 4x3 zone grid over a 4 x 3 m flight area ──────────────────────────
-- Metres relative to the takeoff point, matching the telemetry frame.

insert into public.zones (label, x_min, x_max, y_min, y_max)
select
  chr(65 + row_index) || (col_index + 1)::text,
  -2.0 + col_index * 1.0,
  -2.0 + (col_index + 1) * 1.0,
   1.5 - (row_index + 1) * 1.0,
   1.5 - row_index * 1.0
from generate_series(0, 2) as row_index,
     generate_series(0, 3) as col_index
on conflict (label) do nothing;


-- ── one completed flight, so every page has something real to draw ──────
--
-- Without this the dashboard, Flights, the flight detail charts and Compare all
-- render their empty states, and nobody can tell a working page from a broken
-- one. The numbers are not random: they are shaped like the lab's own readings.
--
--   - The path is the demo lawnmower below, flown at 0.4 m.
--   - z is RELATIVE TO ground_z_m, exactly as the agent stores it. ground_z_m
--     is 1.02, a real-looking Lighthouse floor (measured 0.85–1.40 across runs
--     in the same room), so anyone who subtracts it a second time gets an
--     obviously wrong -0.6 m instead of a plausible number.
--   - raw_temp reads ~6 degrees warm, because the drone heats its own sensor.
--     corrected_temp is what the correction engine would produce. A seed where
--     the two are equal would hide the entire point of that module.

insert into public.flights (
  id, drone_id, created_by, status, temp_unit,
  ambient_start, ground_z_m, csv_path, started_at, ended_at
)
values (
  '33333333-3333-3333-3333-333333333333',
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111',
  'completed', 'C',
  22.0, 1.02,
  'organized_flights/seed-demo-lawnmower.csv',
  now() - interval '2 hours',
  now() - interval '2 hours' + interval '180 seconds'
)
on conflict (id) do nothing;

-- 180 samples at 1 Hz along the five legs of the lawnmower.
insert into public.telemetry (
  flight_id, index, recorded_at, mode, thermal_state, temp_unit,
  raw_temp, corrected_temp, expected_raw, deviation, thermal_offset,
  ambient_est, roc_per_s,
  station_pressure_hpa, sea_level_pressure_hpa, air_density_kg_m3,
  pressure_altitude_m, battery_v, thrust, x_m, y_m, z_m
)
select
  '33333333-3333-3333-3333-333333333333',
  i,
  now() - interval '2 hours' + (i || ' seconds')::interval,
  'auto',
  case when i < 20 then 'warming' else 'steady' end,
  'C',
  -- Raw climbs as the board warms, then plateaus; corrected stays near ambient.
  round((28.1 + least(i, 60) * 0.012 + sin(i / 9.0) * 0.06)::numeric, 3),
  round((22.0 + sin(i / 11.0) * 0.18 + (i * 0.0016))::numeric, 3),
  round((28.0 + least(i, 60) * 0.012)::numeric, 3),
  round((sin(i / 9.0) * 0.06)::numeric, 3),
  round((6.1 + least(i, 60) * 0.004)::numeric, 3),
  round((22.0 + (i * 0.0016))::numeric, 3),
  round((case when i < 20 then 0.012 else 0.0007 end)::numeric, 4),
  round((1013.2 - sin(i / 30.0) * 0.4)::numeric, 3),
  round((1015.6 - sin(i / 30.0) * 0.4)::numeric, 3),
  round((1.1885 + sin(i / 25.0) * 0.0009)::numeric, 5),
  round((-18.0 + sin(i / 30.0) * 3.0)::numeric, 3),
  -- A LiPo under load: a steep first drop, then a long shallow slope.
  round((4.05 - 0.10 * (1 - exp(-i / 14.0)) - i * 0.00118)::numeric, 3),
  (37200 + (sin(i / 7.0) * 520))::integer,
  round(x0 + (x1 - x0) * t, 3),
  round(y0 + (y1 - y0) * t, 3),
  round((0.400 + sin(i / 6.0) * 0.012)::numeric, 3)
from generate_series(0, 179) as i,
lateral (
  select
    least(i / 36, 4)                         as seg,
    ((i % 36)::numeric / 36.0)               as t
) as leg,
lateral (
  select
    (array[-1.0, -1.0,  0.0, 0.0, 1.0])[seg + 1]::numeric as x0,
    (array[ 1.0, -1.0, -1.0, 1.0, 1.0])[seg + 1]::numeric as y0,
    (array[-1.0,  0.0,  0.0, 1.0, 1.0])[seg + 1]::numeric as x1,
    (array[-1.0, -1.0,  1.0, 1.0, -1.0])[seg + 1]::numeric as y1
) as pts
on conflict (flight_id, index) do nothing;

-- One prediction per zone, so the zone map and Compare have values to colour.
-- health_score is 0–1 — the range the dashboard's sequential ramp assumes. See
-- docs/features/frontend/operator-dashboard.txt.
insert into public.predictions (
  flight_id, zone_id, health_score, disease_risk, label, model, sample_count, notes
)
select
  '33333333-3333-3333-3333-333333333333',
  z.id,
  round((0.55 + 0.42 * abs(sin(('x' || substr(md5(z.label), 1, 8))::bit(32)::int / 900.0)))::numeric, 3),
  round((0.05 + 0.30 * abs(cos(('x' || substr(md5(z.label), 1, 8))::bit(32)::int / 700.0)))::numeric, 3),
  'seed',
  'lnn',
  15,
  'Seeded demo values — not model output.'
from public.zones z
on conflict do nothing;


-- ── one queued mission, so the agent poller has something to find ───────

insert into public.missions (name, type, plan, created_by, status)
values (
  'demo lawnmower',
  'lawnmower',
  jsonb_build_object(
    'type', 'lawnmower',
    'name', 'demo lawnmower',
    'altitude_m', 0.4,
    'hold_s', 0.0,
    'leg_duration_s', 3.0,
    'return_to_start', true,
    'metadata', jsonb_build_object('width_m', 2.0, 'height_m', 2.0, 'step_m', 1.0),
    'waypoints', jsonb_build_array(
      jsonb_build_object('x', -1.0, 'y',  1.0, 'z', 0.4, 'label', 'L1-1'),
      jsonb_build_object('x', -1.0, 'y', -1.0, 'z', 0.4, 'label', 'L1-1'),
      jsonb_build_object('x',  0.0, 'y', -1.0, 'z', 0.4, 'label', 'L1-2'),
      jsonb_build_object('x',  0.0, 'y',  1.0, 'z', 0.4, 'label', 'L1-2'),
      jsonb_build_object('x',  1.0, 'y',  1.0, 'z', 0.4, 'label', 'L1-3'),
      jsonb_build_object('x',  1.0, 'y', -1.0, 'z', 0.4, 'label', 'L1-3')
    )
  ),
  '11111111-1111-1111-1111-111111111111',
  'queued'
);
