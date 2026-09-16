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

insert into auth.users (
  instance_id, id, aud, role, email,
  encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data,
  created_at, updated_at
)
values (
  '00000000-0000-0000-0000-000000000000',
  '11111111-1111-1111-1111-111111111111',
  'authenticated', 'authenticated', 'operator@cropwatcher.local',
  crypt('cropwatcher', gen_salt('bf')),
  now(),
  '{"provider":"email","providers":["email"]}',
  '{"full_name":"Demo Operator"}',
  now(), now()
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
