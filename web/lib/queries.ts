import "server-only";
import { cache } from "react";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { LOGIN } from "@/lib/routes";
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
 * An expired sign-in is not an error page. It is a sign-in.
 *
 * A session that runs out while a tab is open fails the NEXT read, and a read
 * that throws lands on error.tsx — which asks the operator to work out for
 * themselves that they need to sign in again. It also happens on a refresh
 * token that was rotated by a request running in parallel: two requests carry
 * the same token, the second is told it was already used, and a page that was
 * working a second ago throws.
 *
 * Either way the answer is the same, so it is taken here: send them to sign in
 * and bring them back. Anything they had typed is still in the browser, and
 * the editor offers it on return (components/admin/useDraft.ts).
 */
function signInAgain(cause: { message?: string; code?: string }, what: string): never {
  console.error(`sign-in expired while reading ${what}`, cause.code, cause.message);
  redirect(LOGIN);
}

function isExpiredSession(cause: { message?: string; code?: string }): boolean {
  const code = cause.code ?? "";
  const message = (cause.message ?? "").toLowerCase();
  return (
    code === "PGRST301" ||
    message.includes("jwt expired") ||
    message.includes("jwt is expired") ||
    message.includes("invalid refresh token") ||
    message.includes("refresh token not found") ||
    message.includes("already used")
  );
}

/** Every admin read ends here: sign in again, or say the read failed. */
function failed(cause: { message: string; code?: string }, what: string): never {
  if (isExpiredSession(cause)) signInAgain(cause, what);
  throw new QueryError(what, cause);
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
  if (error) failed(error, "flights");
  return data;
});

export const getFlight = cache(async (id: string): Promise<FlightRow | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("flights")
    .select("*")
    .eq("id", id)
    .maybeSingle();
  if (error) failed(error, "this flight");
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
    if (error) failed(error, "telemetry");
    return data;
  },
);

/** One recorded camera frame of a session, as the flight page shows it. */
export type SessionFrame = {
  seq: number;
  /** A signed link — the bucket is private. Valid for FRAME_LINK_S. */
  url: string;
  /** Seconds since the session started, and where the drone thought it was. */
  t_s: number | null;
  x_m: number | null;
  y_m: number | null;
  z_m: number | null;
};

/** How long a signed frame link lives — long enough to page through a session. */
const FRAME_LINK_S = 60 * 60;
const FRAMES_BUCKET = "flight-frames";

/**
 * A session's recorded camera frames, from the private flight-frames bucket.
 *
 * The desktop agent writes every frame to disk and uploads two a second, with
 * a frames.csv index (backend/agent/cropwatcher/camera/recording.py). The index
 * gives each frame its time and position; a frame whose index row has not
 * arrived yet still shows, without them. Empty when the session recorded none.
 */
export const getSessionFrames = cache(async (sessionId: string): Promise<SessionFrame[]> => {
  const supabase = await createClient();
  const bucket = supabase.storage.from(FRAMES_BUCKET);
  const { data: files, error } = await bucket.list(`${sessionId}/frames`, {
    limit: 2000,
    sortBy: { column: "name", order: "asc" },
  });
  if (error) failed({ message: error.message }, "camera frames");
  const names = (files ?? []).map((f) => f.name).filter((n) => /^\d+\.(png|jpg)$/.test(n));
  if (names.length === 0) return [];

  const { data: signed, error: signError } = await bucket.createSignedUrls(
    names.map((n) => `${sessionId}/frames/${n}`), FRAME_LINK_S);
  if (signError) failed({ message: signError.message }, "camera frame links");

  // The index is optional: the frames are the record, the index annotates it.
  const where = new Map<number, Pick<SessionFrame, "t_s" | "x_m" | "y_m" | "z_m">>();
  const { data: csv } = await bucket.download(`${sessionId}/frames.csv`);
  if (csv) {
    const [header, ...rows] = (await csv.text()).trim().split("\n");
    const col = header.split(",");
    const num = (v: string | undefined) => (v === undefined || v === "" ? null : Number(v));
    for (const row of rows) {
      const cells = row.split(",");
      const get = (name: string) => cells[col.indexOf(name)];
      where.set(Number(get("seq")), {
        t_s: num(get("t_s")), x_m: num(get("x_m")), y_m: num(get("y_m")), z_m: num(get("z_m")),
      });
    }
  }

  return names.flatMap((name, i) => {
    const url = signed?.[i]?.signedUrl;
    if (!url) return [];
    const seq = Number(name.split(".")[0]);
    return [{ seq, url, ...(where.get(seq) ?? { t_s: null, x_m: null, y_m: null, z_m: null }) }];
  });
});

export const getZones = cache(async (): Promise<ZoneRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("zones").select("*").order("label");
  if (error) failed(error, "zones");
  return data;
});

export const getMissions = cache(async (limit = 50): Promise<MissionRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("missions")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) failed(error, "missions");
  return data;
});

export const getPredictionsForFlight = cache(
  async (flightId: string): Promise<PredictionRow[]> => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("predictions")
      .select("*")
      .eq("flight_id", flightId);
    if (error) failed(error, "predictions");
    return data;
  },
);

export type DroneRow = Database["public"]["Tables"]["drones"]["Row"];

export const getDrones = cache(async (): Promise<DroneRow[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase.from("drones").select("*").order("name");
  if (error) failed(error, "drones");
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
  if (error) failed(error, "the running flight");
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
    if (error) failed(error, "zone health");

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
    failed(error, "projects");
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
    failed(error, "the team");
  }
  return data;
});

/** One person, by the slug in their URL. */
export const getTeamMemberBySlug = cache(
  async (slug: string): Promise<TeamMemberRow | null> => {
    const supabase = await createClient();
    const { data, error } = await supabase
      .from("team_members")
      .select("*")
      .eq("slug", slug)
      .maybeSingle();
    if (error) {
      if (missingTable(error)) return null;
      failed(error, "this team member");
    }
    return data;
  },
);

/**
 * The published projects a person worked on, in the order they are listed on
 * each project. A draft is filtered out here as well as by RLS: an operator
 * reading a public page should see the public page.
 */
export const getProjectsForMember = cache(async (memberId: string): Promise<ProjectCard[]> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("project_members")
    .select(`display_order, projects(${CARD_COLUMNS})`)
    .eq("member_id", memberId)
    .order("display_order", { ascending: true });
  if (error) {
    if (missingTable(error)) return [];
    failed(error, "this person's projects");
  }
  return data
    .map((row) => row.projects as ProjectCard | null)
    .filter((p): p is ProjectCard => p !== null && p.status === "published");
});

async function teamFor(projectId: string): Promise<TeamMemberRow[]> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("project_members")
    .select("display_order, team_members(*)")
    .eq("project_id", projectId)
    .order("display_order", { ascending: true });
  if (error) failed(error, "this project's team");
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
      failed(error, "this project");
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
  if (error) failed(error, "projects");
  return data;
});

export const getProjectByIdAdmin = cache(
  async (id: string): Promise<ProjectWithTeam | null> => {
    const supabase = await createClient();
    const { data, error } = await supabase.from("projects").select("*").eq("id", id).maybeSingle();
    if (error) failed(error, "this project");
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
    failed(error, "the gallery");
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
    failed(error, "this album");
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
  if (error) failed(error, "albums");
  return data.map(toCard);
});

export const getAlbumByIdAdmin = cache(async (id: string): Promise<AlbumWithItems | null> => {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums")
    .select("*, gallery_items(*)")
    .eq("id", id)
    .maybeSingle();
  if (error) failed(error, "this album");
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
  if (error) failed(error, "the pages");
  return new Map(data.map((row) => [row.key, row.updated_at]));
});
