"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { Database } from "@/types/database";

const PLACEHOLDER_URL = "https://your-project-ref.supabase.co";

/**
 * Whether Supabase is actually configured, as opposed to still holding the
 * values from `.env.example`.
 *
 * Checked rather than assumed so the public showcase still renders on a fresh
 * clone: a missing key should degrade the operator area, not blank the site.
 */
export function isSupabaseConfigured(): boolean {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anon) return false;
  if (url === PLACEHOLDER_URL) return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function createClient() {
  if (!isSupabaseConfigured()) {
    throw new Error(
      "Supabase is not configured. Fill NEXT_PUBLIC_SUPABASE_URL and " +
        "NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local.",
    );
  }
  return createBrowserClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
