import "server-only";
import { cache } from "react";
import { createClient } from "@/lib/supabase/server";
import type { Database } from "@/types/database";

export type FlightRow = Database["public"]["Tables"]["flights"]["Row"];
export type TelemetryRow = Database["public"]["Tables"]["telemetry"]["Row"];
export type MissionRow = Database["public"]["Tables"]["missions"]["Row"];
export type ZoneRow = Database["public"]["Tables"]["zones"]["Row"];
export type PredictionRow = Database["public"]["Tables"]["predictions"]["Row"];
export type ProfileRow = Database["public"]["Tables"]["profiles"]["Row"];

/**
 * Every read goes through this file.
 *
 * Two reasons it is worth the indirection. It keeps `createClient()` out of
 * components, so a later static export (a Tauri mobile build) swaps one file
 * instead of thirty. And it gives every query a single place to be cached and
 * typed.
 *
 * `cache()` memoises per request, so a layout and a page asking for the same
 * flight cost one round trip.
 */

export const getCurrentProfile = cache(async (): Promise<ProfileRow | null> => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;

  const { data } = await supabase
    .from("profiles")
    .select("*")
    .eq("id", user.id)
    .maybeSingle();

  return data ?? null;
});

export const isOperator = cache(async (): Promise<boolean> => {
  const profile = await getCurrentProfile();
  return profile?.role === "operator";
});

export const getRecentFlights = cache(async (limit = 20): Promise<FlightRow[]> => {
  const supabase = await createClient();
  const { data } = await supabase
    .from("flights")
    .select("*")
    .order("started_at", { ascending: false })
    .limit(limit);
  return data ?? [];
});

export const getFlight = cache(async (id: string): Promise<FlightRow | null> => {
  const supabase = await createClient();
  const { data } = await supabase
    .from("flights")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  return data ?? null;
});

/**
 * Telemetry for one flight, in order.
 *
 * Capped: a 2-minute flight at 10 Hz is 1200 rows, but nothing stops someone
 * flying for ten minutes, and an uncapped select would send every row to the
 * browser to draw a chart a few hundred pixels wide.
 */
export const getFlightTelemetry = cache(
  async (flightId: string, limit = 5000): Promise<TelemetryRow[]> => {
    const supabase = await createClient();
    const { data } = await supabase
      .from("telemetry")
      .select("*")
      .eq("flight_id", flightId)
      .order("index", { ascending: true })
      .limit(limit);
    return data ?? [];
  },
);

export const getZones = cache(async (): Promise<ZoneRow[]> => {
  const supabase = await createClient();
  const { data } = await supabase.from("zones").select("*").order("label");
  return data ?? [];
});

export const getMissions = cache(async (limit = 50): Promise<MissionRow[]> => {
  const supabase = await createClient();
  const { data } = await supabase
    .from("missions")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(limit);
  return data ?? [];
});

export const getPredictionsForFlight = cache(
  async (flightId: string): Promise<PredictionRow[]> => {
    const supabase = await createClient();
    const { data } = await supabase
      .from("predictions")
      .select("*")
      .eq("flight_id", flightId);
    return data ?? [];
  },
);

/** Dashboard summary. One call, so the landing view is a single round trip. */
export const getDashboardSummary = cache(async () => {
  const [flights, zones, missions] = await Promise.all([
    getRecentFlights(5),
    getZones(),
    getMissions(5),
  ]);

  const latest = flights[0] ?? null;
  const telemetry = latest ? await getFlightTelemetry(latest.id, 2000) : [];

  return {
    latest,
    flightCount: flights.length,
    zoneCount: zones.length,
    queued: missions.filter((m) => m.status === "queued").length,
    sampleCount: telemetry.length,
    telemetry,
  };
});
