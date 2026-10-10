"use client";

import { createClient } from "@/lib/supabase/client";

/**
 * A browser client whose Realtime socket carries the signed-in user's token.
 *
 * The SSR browser client loads its session from cookies lazily. A channel
 * subscribed before that finishes joins as `anon`, and since anon has no SELECT
 * on any table, RLS delivers nothing — while the channel still reports
 * SUBSCRIBED. Measured: a page subscribed this way received 0 of the rows
 * written during a 5 s window; a client that set the token first received 16
 * of 16. So the token is set explicitly, and a missing session is an error,
 * not a quiet empty stream.
 *
 * Shared by the live telemetry view (lib/use-live-telemetry.ts) and the
 * notifications (components/operator/notifications.tsx) — Realtime is a
 * long-lived socket owned by a component, the one reason a client is made
 * outside lib/queries.ts.
 */
export async function authedRealtimeClient() {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) return null;
  await supabase.realtime.setAuth(session.access_token);
  return supabase;
}
