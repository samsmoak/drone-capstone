import "server-only";
import { cache } from "react";
import { createClient } from "@/lib/supabase/server";
import type { Database } from "@/types/database";
import { normalizeContent, type ContentObject, type PageKey } from "@/lib/site-content";

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

// ── portfolio ────────────────────────────────────────────────────────────
//
// Ported from ../doctor-portfolio. The public pages must never blank: Vercel
// deploys code before a hand-run migration reaches the database, so the public
// readers return an empty list when the tables are missing (Postgres 42P01 /
// PostgREST PGRST205) and throw on anything else.

export type ProjectRow = Database["public"]["Tables"]["projects"]["Row"];
export type TeamMemberRow = Database["public"]["Tables"]["team_members"]["Row"];
export type ProjectCard = Omit<ProjectRow, "content">;
export type ProjectWithTeam = ProjectRow & { team: TeamMemberRow[] };

const CARD_COLUMNS =
  "id, slug, title, subtitle, summary, cover_image_url, category, date_label, location, status, display_order, published_at, created_at, updated_at";

function missingTable(error: { code?: string }): boolean {
  return error.code === "42P01" || error.code === "PGRST205";
}

export const getPublishedProjects = cache(async (): Promise<ProjectCard[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("projects")
    .select(CARD_COLUMNS)
    .eq("status", "published")
    .order("display_order", { ascending: true })
    .order("created_at", { ascending: false });
  if (error) {
    if (missingTable(error)) return [];
    throw new QueryError("projects", error);
  }
  return data;
});

/** Team members, in display order. */
export const getTeamMembers = cache(async (): Promise<TeamMemberRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("team_members")
    .select("*")
    .order("display_order", { ascending: true })
    .order("created_at", { ascending: true });
  if (error) {
    if (missingTable(error)) return [];
    throw new QueryError("the team", error);
  }
  return data;
});

async function teamFor(projectId: string): Promise<TeamMemberRow[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("project_members")
    .select("display_order, team_members(*)")
    .eq("project_id", projectId)
    .order("display_order", { ascending: true });
  if (error) throw new QueryError("this project's team", error);
  return data
    .map((row) => row.team_members as TeamMemberRow | null)
    .filter((m): m is TeamMemberRow => m !== null);
}

export const getPublishedProjectBySlug = cache(
  async (slug: string): Promise<ProjectWithTeam | null> => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("projects")
      .select("*")
      .eq("slug", slug)
      .eq("status", "published")
      .maybeSingle();
    if (error) {
      if (missingTable(error)) return null;
      throw new QueryError("this project", error);
    }
    if (!data) return null;
    return { ...data, team: await teamFor(data.id) };
  },
);

/** Admin: every project, drafts included. RLS shows drafts to operators only. */
export const getAllProjectsAdmin = cache(async (): Promise<ProjectCard[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("projects")
    .select(CARD_COLUMNS)
    .order("display_order", { ascending: true })
    .order("created_at", { ascending: false });
  if (error) throw new QueryError("projects", error);
  return data;
});

export const getProjectByIdAdmin = cache(
  async (id: string): Promise<ProjectWithTeam | null> => {
    const supabase = await createClient();
    const { data, error } = await supabase.from("projects").select("*").eq("id", id).maybeSingle();
    if (error) throw new QueryError("this project", error);
    if (!data) return null;
    return { ...data, team: await teamFor(data.id) };
  },
);

// ── gallery ──────────────────────────────────────────────────────────────
//
// Albums of photos and videos (migration 0008). Same rule as the portfolio:
// public readers return empty when the tables are missing, admin readers throw.

export type AlbumRow = Database["public"]["Tables"]["gallery_albums"]["Row"];
export type GalleryItemRow = Database["public"]["Tables"]["gallery_items"]["Row"];
export type AlbumCard = AlbumRow & {
  photoCount: number;
  videoCount: number;
  /** Up to three images for the card's mosaic, in album order. */
  preview: GalleryItemRow[];
};
export type AlbumWithItems = AlbumRow & { items: GalleryItemRow[] };

function toCard(album: AlbumRow & { gallery_items: GalleryItemRow[] | null }): AlbumCard {
  const items = [...(album.gallery_items ?? [])].sort((a, b) => a.display_order - b.display_order);
  const { gallery_items: _items, ...row } = album;
  void _items;
  return {
    ...row,
    photoCount: items.filter((i) => i.kind === "image").length,
    videoCount: items.filter((i) => i.kind === "video").length,
    preview: items.filter((i) => i.kind === "image").slice(0, 3),
  };
}

export const getPublishedAlbums = cache(async (): Promise<AlbumCard[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums")
    .select("*, gallery_items(*)")
    .eq("status", "published")
    .order("display_order", { ascending: true });
  if (error) {
    if (missingTable(error)) return [];
    throw new QueryError("the gallery", error);
  }
  return data.map(toCard);
});

export const getPublishedAlbumBySlug = cache(async (slug: string): Promise<AlbumWithItems | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums")
    .select("*, gallery_items(*)")
    .eq("slug", slug)
    .eq("status", "published")
    .maybeSingle();
  if (error) {
    if (missingTable(error)) return null;
    throw new QueryError("this album", error);
  }
  if (!data) return null;
  const { gallery_items, ...album } = data;
  return { ...album, items: [...(gallery_items ?? [])].sort((a, b) => a.display_order - b.display_order) };
});

export const getAllAlbumsAdmin = cache(async (): Promise<AlbumCard[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums")
    .select("*, gallery_items(*)")
    .order("display_order", { ascending: true });
  if (error) throw new QueryError("albums", error);
  return data.map(toCard);
});

export const getAlbumByIdAdmin = cache(async (id: string): Promise<AlbumWithItems | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums")
    .select("*, gallery_items(*)")
    .eq("id", id)
    .maybeSingle();
  if (error) throw new QueryError("this album", error);
  if (!data) return null;
  const { gallery_items, ...album } = data;
  return { ...album, items: [...(gallery_items ?? [])].sort((a, b) => a.display_order - b.display_order) };
});

// ── editable page wording ────────────────────────────────────────────────

/**
 * A public page's wording: the stored override normalised against the page's
 * spec, or its defaults. Never throws — a public page must render even if the
 * table is missing or the read fails; the failure is logged.
 */
export const getPageContent = cache(async (key: PageKey): Promise<ContentObject> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("site_pages").select("content").eq("key", key).maybeSingle();
  if (error && !missingTable(error)) console.error(`page content read failed: ${key}`, error.code, error.message);
  return normalizeContent(key, data?.content ?? null);
});

/** Admin: which pages carry an override, and when each was last edited. */
export const getEditedPages = cache(async (): Promise<Map<string, string>> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("site_pages").select("key, updated_at");
  if (error) throw new QueryError("the pages", error);
  return new Map(data.map((row) => [row.key, row.updated_at]));
});
