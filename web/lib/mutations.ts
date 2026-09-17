"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { ADMIN_GALLERY, ADMIN_PROJECTS, ADMIN_TEAM, FLIGHTS, GALLERY, HOME, PLAN, PROJECTS, TEAM } from "@/lib/routes";
import { youtubeId } from "@/lib/video";
import { PAGE_SPECS, isPageKey, normalizeContent } from "@/lib/site-content";
import * as profile from "@/lib/team-profile";
import type { Json } from "@/types/database";
import { getZones } from "@/lib/queries";
import { buildPlan, parsePlanInput, validatePlan } from "@/lib/mission-plan";

/**
 * Every write goes through this file.
 *
 * These are Server Actions, so they run with the caller's cookie-bound session
 * and RLS applies. The role checks here are for a useful error message; the
 * enforcement is `is_operator()` in Postgres. Never move enforcement up here —
 * a client can call the API directly.
 */

export type ActionResult =
  | { ok: true; id?: string }
  | { ok: false; error: string };

/**
 * Queue a mission built in the planner.
 *
 * Takes zone ids and settings, never waypoints. The plan is rebuilt here from
 * the zones table and validated with the same rules the planner shows, because
 * a Server Action is a public endpoint: whatever the browser claims to have
 * built, only what the server builds reaches the agent. RLS still decides
 * whether this user may insert at all.
 */
export async function queuePlannedMission(raw: unknown): Promise<ActionResult & { problems?: string[] }> {
  const input = parsePlanInput(raw);
  if (!input) return { ok: false, error: "That plan could not be read. Reload the page and try again." };

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not signed in." };

  let zones;
  try {
    zones = await getZones();
  } catch {
    return { ok: false, error: "Could not load the zones to check this plan. Please try again." };
  }

  const unknown = input.zoneIds.filter((id) => !zones.some((z) => z.id === id));
  if (unknown.length > 0) {
    return { ok: false, error: "Some chosen zones no longer exist. Reload the page and choose again." };
  }

  const plan = buildPlan(input, zones);
  const problems = validatePlan(plan);
  if (problems.length > 0) {
    return { ok: false, error: "This plan is not safe to queue yet.", problems };
  }

  const { data, error } = await supabase
    .from("missions")
    .insert({ name: plan.name, type: plan.type, plan: plan as never, created_by: user.id })
    .select("id")
    .single();

  if (error) {
    const friendly =
      error.code === "42501"
        ? "Your account is not an operator, so it cannot queue flights."
        : "Could not queue the mission. Please try again.";
    return { ok: false, error: friendly };
  }

  revalidatePath(PLAN);
  return { ok: true, id: data.id };
}

export async function cancelMission(missionId: string): Promise<ActionResult> {
  const supabase = await createClient();

  const { data, error } = await supabase
    .from("missions")
    .update({ status: "cancelled" })
    .eq("id", missionId)
    // Only a mission that has not been picked up can be cancelled here.
    // One already claimed is stopped through the agent, not the database.
    .eq("status", "queued")
    // An update that matches nothing is not an error to Postgres — the agent
    // claimed it a moment ago, or RLS filtered it out. Without counting rows
    // the operator is told "cancelled" about a mission that is about to fly.
    .select("id");

  if (error) {
    return { ok: false, error: "Could not cancel that mission." };
  }
  if (data.length === 0) {
    // Refresh anyway: the row on screen still says "queued", and the real
    // status is the most useful thing to show next to this message.
    revalidatePath(PLAN);
    return {
      ok: false,
      error:
        "That mission was not cancelled: it has already been picked up by the agent, or your account cannot change it. Stop a flight in progress from the desktop app.",
    };
  }

  revalidatePath(PLAN);
  return { ok: true };
}

export async function deleteFlight(flightId: string): Promise<ActionResult> {
  const supabase = await createClient();
  const { error } = await supabase.from("flights").delete().eq("id", flightId);

  if (error) {
    return { ok: false, error: "Could not delete that flight." };
  }

  revalidatePath(FLIGHTS);
  return { ok: true };
}

export async function signOut(): Promise<void> {
  const supabase = await createClient();
  await supabase.auth.signOut();
  revalidatePath("/", "layout");
  // To the visitor home: signing out of the operator view would otherwise land
  // on a protected page and bounce to the sign-in form.
  redirect(HOME);
}

// ── portfolio (admin) ────────────────────────────────────────────────────
//
// Ported from ../doctor-portfolio's mutations, single-site. Enforcement is
// public.is_operator() in RLS; the checks here only produce a readable error.

export type PortfolioResult<T = undefined> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function revalidatePortfolio(slug?: string) {
  revalidatePath(PROJECTS);
  if (slug) revalidatePath(`${PROJECTS}/${slug}`);
  revalidatePath(TEAM);
  revalidatePath(ADMIN_PROJECTS);
  revalidatePath(ADMIN_TEAM);
}

/** A person's own page, plus the list that links to it. */
function revalidateMember(slug: string | null) {
  revalidatePath(TEAM);
  if (slug) revalidatePath(`${TEAM}/${slug}`);
  revalidatePath(ADMIN_TEAM);
}

function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .slice(0, 80) || "project"
  );
}

export async function createProject(input: { title: string }): Promise<PortfolioResult<{ id: string }>> {
  const title = input.title.trim();
  if (!title) return { ok: false, error: "Give the project a title." };
  const supabase = await createClient();

  // Unique slug: add -2, -3 … on collision rather than failing the insert.
  const base = slugify(title);
  const { data: taken } = await supabase.from("projects").select("slug").like("slug", `${base}%`);
  const used = new Set((taken ?? []).map((r) => r.slug));
  let slug = base;
  for (let n = 2; used.has(slug); n++) slug = `${base}-${n}`;

  const { data, error } = await supabase
    .from("projects")
    .insert({ title, slug, status: "draft", content: [] })
    .select("id")
    .single();
  if (error) return { ok: false, error: "Could not create the project. Are you signed in as an operator?" };
  revalidatePortfolio();
  return { ok: true, data: { id: data.id } };
}

export type ProjectUpdate = {
  title: string;
  subtitle: string;
  summary: string;
  category: string;
  date_label: string;
  location: string;
  cover_image_url: string | null;
  content: Json;
  status: "draft" | "published";
  member_ids: string[];
};

export async function updateProject(id: string, input: ProjectUpdate): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { data: before } = await supabase
    .from("projects").select("slug, published_at").eq("id", id).maybeSingle();

  const { member_ids, ...fields } = input;
  const { error } = await supabase
    .from("projects")
    .update({
      ...fields,
      updated_at: new Date().toISOString(),
      // Stamped on first publish only, so re-publishing an edit does not
      // silently move the project.
      published_at:
        input.status === "published" ? before?.published_at ?? new Date().toISOString() : before?.published_at ?? null,
    })
    .eq("id", id);
  if (error) return { ok: false, error: "Could not save the project." };

  // The team is replaced as a set, in the order chosen.
  const { error: clearError } = await supabase.from("project_members").delete().eq("project_id", id);
  if (clearError) return { ok: false, error: "Saved the project, but could not update its team." };
  if (member_ids.length > 0) {
    const { error: teamError } = await supabase.from("project_members").insert(
      member_ids.map((member_id, i) => ({ project_id: id, member_id, display_order: i })),
    );
    if (teamError) return { ok: false, error: "Saved the project, but could not update its team." };
  }

  revalidatePortfolio(before?.slug);
  return { ok: true, data: undefined };
}

export async function setProjectStatus(id: string, status: "draft" | "published"): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { data: before } = await supabase.from("projects").select("slug, published_at").eq("id", id).maybeSingle();
  const { error } = await supabase
    .from("projects")
    .update({
      status,
      published_at: status === "published" ? before?.published_at ?? new Date().toISOString() : before?.published_at ?? null,
    })
    .eq("id", id);
  if (error) return { ok: false, error: "Could not change the project's status." };
  revalidatePortfolio(before?.slug);
  return { ok: true, data: undefined };
}

export async function deleteProject(id: string): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { error } = await supabase.from("projects").delete().eq("id", id);
  if (error) return { ok: false, error: "Could not delete the project." };
  revalidatePortfolio();
  return { ok: true, data: undefined };
}

export async function reorderProjects(order: { id: string; position: number }[]): Promise<PortfolioResult> {
  const supabase = await createClient();
  for (const { id, position } of order) {
    const { error } = await supabase.from("projects").update({ display_order: position }).eq("id", id);
    if (error) return { ok: false, error: "Could not reorder the projects." };
  }
  revalidatePortfolio();
  return { ok: true, data: undefined };
}

// MemberInput and EMPTY_MEMBER live in lib/team-profile.ts: a "use server"
// module may export functions only, and the admin form needs the empty value.
type MemberInput = profile.MemberInput;

function cleanMember(input: MemberInput): MemberInput | string {
  const full_name = input.full_name.trim();
  if (!full_name) return "A team member needs a name.";
  const website = input.website_url?.trim() || null;
  if (website && !/^https?:\/\//i.test(website)) return "The website must start with http:// or https://.";
  const email = input.email?.trim() || null;
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return "That email address does not look right.";
  // The slug is this person's URL. Typed freely in the admin, so it is cleaned
  // the same way here — the address bar must never see a space or a slash.
  const slug = profile.slugify(input.slug || full_name);
  if (!slug) return "That name has no letters or numbers to make a web address from — set one by hand.";
  // The three lists go through the same parser the pages read them with, so a
  // row can only ever hold what a page can render (lib/team-profile.ts).
  return {
    ...input,
    full_name,
    slug,
    role: input.role.trim(),
    headline: input.headline.trim(),
    location: input.location.trim(),
    bio: input.bio.trim(),
    about: input.about.trim(),
    current_work: input.current_work.trim(),
    website_url: website,
    email,
    hobbies: profile.hobbies(input.hobbies as unknown as Json),
    links: profile.links(input.links as unknown as Json),
    photos: profile.photos(input.photos as unknown as Json),
  };
}

/** Postgres 23505: two people cannot share a web address. */
function slugTaken(error: { code?: string }): boolean {
  return error.code === "23505";
}

export async function createMember(input: MemberInput): Promise<PortfolioResult<{ id: string }>> {
  const cleaned = cleanMember(input);
  if (typeof cleaned === "string") return { ok: false, error: cleaned };
  const supabase = await createClient();
  const { data: last } = await supabase
    .from("team_members").select("display_order").order("display_order", { ascending: false }).limit(1);
  const { data, error } = await supabase
    .from("team_members")
    .insert({ ...cleaned, hobbies: cleaned.hobbies as unknown as Json,
              links: cleaned.links as unknown as Json, photos: cleaned.photos as unknown as Json,
              display_order: (last?.[0]?.display_order ?? 0) + 1 })
    .select("id")
    .single();
  if (error) {
    return {
      ok: false,
      error: slugTaken(error)
        ? `The web address /team/${cleaned.slug} is already taken. Give this person a different one.`
        : "Could not add the team member.",
    };
  }
  revalidateMember(cleaned.slug);
  return { ok: true, data: { id: data.id } };
}

export async function updateMember(id: string, input: MemberInput): Promise<PortfolioResult> {
  const cleaned = cleanMember(input);
  if (typeof cleaned === "string") return { ok: false, error: cleaned };
  const supabase = await createClient();
  const { error } = await supabase
    .from("team_members")
    .update({ ...cleaned, hobbies: cleaned.hobbies as unknown as Json,
              links: cleaned.links as unknown as Json, photos: cleaned.photos as unknown as Json,
              updated_at: new Date().toISOString() })
    .eq("id", id);
  if (error) {
    return {
      ok: false,
      error: slugTaken(error)
        ? `The web address /team/${cleaned.slug} is already taken. Give this person a different one.`
        : "Could not save the team member.",
    };
  }
  revalidateMember(cleaned.slug);
  return { ok: true, data: undefined };
}

export async function deleteMember(id: string): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { error } = await supabase.from("team_members").delete().eq("id", id);
  if (error) return { ok: false, error: "Could not remove the team member." };
  revalidatePortfolio();
  return { ok: true, data: undefined };
}

export async function reorderMembers(order: { id: string; position: number }[]): Promise<PortfolioResult> {
  const supabase = await createClient();
  for (const { id, position } of order) {
    const { error } = await supabase.from("team_members").update({ display_order: position }).eq("id", id);
    if (error) return { ok: false, error: "Could not reorder the team." };
  }
  revalidatePortfolio();
  return { ok: true, data: undefined };
}

// ── gallery (admin) ──────────────────────────────────────────────────────

function revalidateGallery(slug?: string) {
  revalidatePath(GALLERY);
  if (slug) revalidatePath(`${GALLERY}/${slug}`);
  revalidatePath(ADMIN_GALLERY);
}

export async function createAlbum(input: { title: string }): Promise<PortfolioResult<{ id: string }>> {
  const title = input.title.trim();
  if (!title) return { ok: false, error: "Give the album a title." };
  const supabase = await createClient();
  const base = slugify(title);
  const { data: taken } = await supabase.from("gallery_albums").select("slug").like("slug", `${base}%`);
  const used = new Set((taken ?? []).map((r) => r.slug));
  let slug = base;
  for (let n = 2; used.has(slug); n++) slug = `${base}-${n}`;
  const { data, error } = await supabase
    .from("gallery_albums").insert({ title, slug, status: "draft" }).select("id").single();
  if (error) return { ok: false, error: "Could not create the album. Are you signed in as an operator?" };
  revalidateGallery();
  return { ok: true, data: { id: data.id } };
}

export type AlbumUpdate = {
  title: string;
  summary: string;
  category: string;
  date_label: string;
  cover_image_url: string | null;
  status: "draft" | "published";
};

export async function updateAlbum(id: string, input: AlbumUpdate): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums")
    .update({ ...input, title: input.title.trim(), updated_at: new Date().toISOString() })
    .eq("id", id)
    .select("slug")
    .single();
  if (error) return { ok: false, error: "Could not save the album." };
  revalidateGallery(data.slug);
  return { ok: true, data: undefined };
}

export async function setAlbumStatus(id: string, status: "draft" | "published"): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("gallery_albums").update({ status }).eq("id", id).select("slug").single();
  if (error) return { ok: false, error: "Could not change the album's status." };
  revalidateGallery(data.slug);
  return { ok: true, data: undefined };
}

export async function deleteAlbum(id: string): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { error } = await supabase.from("gallery_albums").delete().eq("id", id);
  if (error) return { ok: false, error: "Could not delete the album." };
  revalidateGallery();
  return { ok: true, data: undefined };
}

export async function reorderAlbums(order: { id: string; position: number }[]): Promise<PortfolioResult> {
  const supabase = await createClient();
  for (const { id, position } of order) {
    const { error } = await supabase.from("gallery_albums").update({ display_order: position }).eq("id", id);
    if (error) return { ok: false, error: "Could not reorder the albums." };
  }
  revalidateGallery();
  return { ok: true, data: undefined };
}

export type NewGalleryItem =
  | { kind: "image"; url: string; width: number | null; height: number | null; caption?: string }
  | { kind: "video"; url: string; caption?: string };

export async function addGalleryItems(albumId: string, items: NewGalleryItem[]): Promise<PortfolioResult> {
  if (items.length === 0) return { ok: true, data: undefined };
  for (const item of items) {
    if (item.kind === "video" && !youtubeId(item.url)) {
      return { ok: false, error: "That is not a YouTube link. Paste a youtube.com or youtu.be address." };
    }
  }
  const supabase = await createClient();
  const { data: last } = await supabase
    .from("gallery_items").select("display_order").eq("album_id", albumId)
    .order("display_order", { ascending: false }).limit(1);
  const start = (last?.[0]?.display_order ?? -1) + 1;
  const { error } = await supabase.from("gallery_items").insert(
    items.map((item, i) => ({
      album_id: albumId,
      kind: item.kind,
      url: item.url.trim(),
      caption: item.caption?.trim() ?? "",
      width: item.kind === "image" ? item.width : null,
      height: item.kind === "image" ? item.height : null,
      display_order: start + i,
    })),
  );
  if (error) return { ok: false, error: "Could not add to the album." };
  const { data: album } = await supabase.from("gallery_albums").select("slug").eq("id", albumId).maybeSingle();
  revalidateGallery(album?.slug);
  return { ok: true, data: undefined };
}

export async function updateGalleryItem(
  id: string, input: { caption: string; credit: string },
): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { error } = await supabase
    .from("gallery_items").update({ caption: input.caption.trim(), credit: input.credit.trim() }).eq("id", id);
  if (error) return { ok: false, error: "Could not save the caption." };
  revalidateGallery();
  return { ok: true, data: undefined };
}

export async function deleteGalleryItem(id: string): Promise<PortfolioResult> {
  const supabase = await createClient();
  const { error } = await supabase.from("gallery_items").delete().eq("id", id);
  if (error) return { ok: false, error: "Could not remove that item." };
  revalidateGallery();
  return { ok: true, data: undefined };
}

export async function reorderGalleryItems(order: { id: string; position: number }[]): Promise<PortfolioResult> {
  const supabase = await createClient();
  for (const { id, position } of order) {
    const { error } = await supabase.from("gallery_items").update({ display_order: position }).eq("id", id);
    if (error) return { ok: false, error: "Could not reorder the album." };
  }
  revalidateGallery();
  return { ok: true, data: undefined };
}

// ── editable page wording (admin) ────────────────────────────────────────

/**
 * Save a page's wording. The content is normalised against the page's spec
 * before it is stored, so only declared fields of the declared type reach the
 * database, whatever the request carried. RLS still decides who may write.
 */
export async function savePageContent(key: string, content: unknown): Promise<PortfolioResult> {
  if (!isPageKey(key)) return { ok: false, error: "There is no such page." };
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not signed in." };
  const { error } = await supabase.from("site_pages").upsert({
    key,
    content: normalizeContent(key, content),
    updated_at: new Date().toISOString(),
    updated_by: user.id,
  });
  if (error) return { ok: false, error: "Could not save the page. Are you signed in as an operator?" };
  revalidatePath(PAGE_SPECS[key].path);
  revalidatePath("/", "layout");            // the footer is on every page
  return { ok: true, data: undefined };
}

/** Back to the wording the page shipped with. */
export async function resetPageContent(key: string): Promise<PortfolioResult> {
  if (!isPageKey(key)) return { ok: false, error: "There is no such page." };
  const supabase = await createClient();
  const { error } = await supabase.from("site_pages").delete().eq("key", key);
  if (error) return { ok: false, error: "Could not reset the page." };
  revalidatePath(PAGE_SPECS[key].path);
  revalidatePath("/", "layout");
  return { ok: true, data: undefined };
}
