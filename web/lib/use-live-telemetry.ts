"use client";

import { useEffect } from "react";
import { createClient, isSupabaseConfigured } from "@/lib/supabase/client";
import { useLiveStore } from "@/lib/store";
import type { TelemetryRow } from "@/lib/queries";

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
 */
async function authedRealtimeClient() {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) return null;
  await supabase.realtime.setAuth(session.access_token);
  return supabase;
}

/**
 * Subscribe to telemetry as the agent writes it.
 *
 * This is the one place a Supabase client is created outside `lib/queries.ts`,
 * and it is deliberate: Realtime is a long-lived socket owned by a component's
 * lifecycle, not a request-scoped read.
 *
 * Authorization is unchanged — the socket carries the user's session and the
 * same RLS policy that guards a `select` guards this stream. A signed-out
 * browser receives nothing rather than everything.
 *
 * Every failure mode sets a status the UI can render. A live view that has
 * silently stopped updating is indistinguishable from a drone sitting still,
 * which is the dangerous reading.
 */
export function useLiveTelemetry(flightId: string | null, initial: TelemetryRow[]) {
  const push = useLiveStore((s) => s.push);
  const reset = useLiveStore((s) => s.reset);
  const setStatus = useLiveStore((s) => s.setStatus);

  useEffect(() => {
    if (!isSupabaseConfigured()) {
      setStatus("error", "Supabase is not configured in this deployment.");
      return;
    }
    if (!flightId) {
      reset(null);
      setStatus("idle");
      return;
    }

    reset(flightId, initial);
    setStatus("connecting");

    let cancelled = false;
    let cleanup: (() => void) | null = null;

    void (async () => {
      const supabase = await authedRealtimeClient();
      if (cancelled) return;
      if (!supabase) {
        setStatus("error", "Your session has expired. Sign in again to see live readings.");
        return;
      }

      const channel = supabase
        .channel(`telemetry:${flightId}`)
        .on(
          "postgres_changes",
          {
            event: "INSERT",
            schema: "public",
            table: "telemetry",
            // Filtered server-side: another flight's rows never reach this socket.
            filter: `flight_id=eq.${flightId}`,
          },
          (payload) => push(payload.new as TelemetryRow),
        )
        .subscribe(async (status) => {
          if (status === "SUBSCRIBED") {
            // Close the gap between the page's server read and this socket
            // opening: rows written in between arrive on neither. Fetch
            // everything after the last index we hold; `push` drops duplicates.
            const lastIndex = useLiveStore.getState().rows.at(-1)?.index ?? -1;
            const { data, error } = await supabase
              .from("telemetry")
              .select("*")
              .eq("flight_id", flightId)
              .gt("index", lastIndex)
              .order("index", { ascending: true });
            if (cancelled) return;
            if (error) {
              setStatus("error", "Connected, but could not load the readings so far.");
              return;
            }
            data.forEach(push);
            setStatus("live");
          } else if (status === "CHANNEL_ERROR") {
            setStatus("error", "Lost the connection to the live feed.");
          } else if (status === "TIMED_OUT") {
            setStatus("error", "The live feed timed out.");
          }
        });

      cleanup = () => void supabase.removeChannel(channel);
    })();

    return () => {
      cancelled = true;
      cleanup?.();
    };
    // `initial` seeds the buffer once per flight; a new array from a refresh
    // must not wipe rows the stream has already delivered.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flightId, push, reset, setStatus]);
}

/**
 * Refresh the page when a flight starts or finishes.
 *
 * The live page is only useful if it notices the drone taking off without the
 * operator reloading. Flight rows are few, so every change triggers `onChange`.
 */
export function useFlightChanges(onChange: () => void) {
  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    let cancelled = false;
    let cleanup: (() => void) | null = null;

    void (async () => {
      // Same reason as the telemetry stream: unauthenticated, this receives nothing.
      const supabase = await authedRealtimeClient();
      if (cancelled || !supabase) return;
      const channel = supabase
        .channel("flights:changes")
        .on("postgres_changes", { event: "*", schema: "public", table: "flights" }, () => onChange())
        .subscribe();
      cleanup = () => void supabase.removeChannel(channel);
    })();

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [onChange]);
}
