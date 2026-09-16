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
 * A read that failed, as opposed to a read that found nothing.
 *
 * Reads throw rather than returning `data ?? []`. An empty fallback turns a
 * database error into an empty list — "No flights recorded yet" when the truth
 * is "could not ask" — and silence is the dangerous state for an operator about
 * to fly. The route's `error.tsx` says what happened instead.
 *
 * The Postgres message is logged server-side and never sent to the browser: it
 * can carry column names and policy internals.
 */
export class QueryError extends Error {
  constructor(what: string, cause: { message: string; code?: string }) {
    console.error(`query failed: ${what}`, cause.code, cause.message);
    super(`Could not load ${what}.`);
    this.name = "QueryError";
  }
}

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
  const { data, error } = await supabase
    .from("flights")
    .select("*")
    .order("started_at", { ascending: false })
    .limit(limit);
  if (error) throw new QueryError("flights", error);
  return data;
});

export const getFlight = cache(async (id: string): Promise<FlightRow | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("flights")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new QueryError("this flight", error);
  return data;
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
    const { data, error } = await supabase
      .from("telemetry")
      .select("*")
      .eq("flight_id", flightId)
      .order("index", { ascending: true })
      .limit(limit);
    if (error) throw new QueryError("telemetry", error);
    return data;
  },
);

export const getZones = cache(async (): Promise<ZoneRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("zones").select("*").order("label");
  if (error) throw new QueryError("zones", error);
  return data;
});

export const getMissions = cache(async (limit = 50): Promise<MissionRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("missions")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) throw new QueryError("missions", error);
  return data;
});

export const getPredictionsForFlight = cache(
  async (flightId: string): Promise<PredictionRow[]> => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("predictions")
      .select("*")
      .eq("flight_id", flightId);
    if (error) throw new QueryError("predictions", error);
    return data;
  },
);

export type DroneRow = Database["public"]["Tables"]["drones"]["Row"];

export const getDrones = cache(async (): Promise<DroneRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("drones").select("*").order("name");
  if (error) throw new QueryError("drones", error);
  return data;
});

/**
 * The flight in progress, if any.
 *
 * Newest `running` flight only. A flight the agent never closed (a crash
 * mid-flight) stays `running` forever, so the live page shows its start time
 * and lets the operator judge whether it is really in the air.
 */
export const getRunningFlight = cache(async (): Promise<FlightRow | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("flights")
    .select("*")
    .eq("status", "running")
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw new QueryError("the running flight", error);
  return data;
});

/**
 * The most recent health estimate for each zone, keyed by zone id.
 *
 * "Most recent" per zone, not "from the most recent flight": a flight that
 * covered only half the greenhouse must not blank the other half's estimates.
 * Bounded, newest first, reduced here — a zone missing from the result has no
 * estimate in that window, and the map says so.
 */
export const getLatestZoneHealth = cache(
  async (limit = 1000): Promise<Map<string, PredictionRow>> => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("predictions")
      .select("*")
      .not("zone_id", "is", null)
      .order("created_at", { ascending: false })
      .limit(limit);
    if (error) throw new QueryError("zone health", error);

    const latest = new Map<string, PredictionRow>();
    for (const row of data) {
      if (row.zone_id && !latest.has(row.zone_id)) latest.set(row.zone_id, row);
    }
    return latest;
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
