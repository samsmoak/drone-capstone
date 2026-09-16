#!/usr/bin/env bash
#
# Link this repo to a hosted Supabase project, apply the schema, and print the
# env vars Vercel needs.
#
# Prerequisite: `supabase login` (an account-level browser login — the project
# keys in another repo's .env cannot do this).
#
#   ./scripts/setup-supabase.sh <project-ref>
#
# Creates nothing destructive: `db push` applies migrations forward. It does
# NOT run `db reset`, which drops everything and is for local use only.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/backend"

if ! supabase projects list >/dev/null 2>&1; then
  echo "Not logged in. Run:  supabase login" >&2
  exit 1
fi

REF="${1:-}"
if [ -z "$REF" ]; then
  echo "Which project? Pick a ref from below, then re-run with it:" >&2
  echo >&2
  supabase projects list >&2
  echo >&2
  echo "  ./scripts/setup-supabase.sh <project-ref>" >&2
  exit 1
fi

echo "==> linking to $REF"
supabase link --project-ref "$REF"

echo "==> applying migrations"
supabase db push

echo "==> regenerating TypeScript types from the live schema"
supabase gen types typescript --linked > "$REPO_ROOT/web/types/database.ts"

echo
echo "==> Vercel environment variables"
echo "    Settings -> Environment Variables. Also set Root Directory to 'web'."
echo
echo "    NEXT_PUBLIC_SUPABASE_URL=https://${REF}.supabase.co"
echo "    NEXT_PUBLIC_SUPABASE_ANON_KEY=<Project Settings -> API -> anon/publishable>"
echo "    NEXT_PUBLIC_SITE_URL=<your vercel domain>"
echo
echo "The seed is NOT applied to a hosted project on purpose: it inserts a demo"
echo "account with a public password. Create your real accounts by signing up"
echo "through the app, then promote one:"
echo
echo "    update public.profiles set role = 'operator' where email = 'you@example.com';"
