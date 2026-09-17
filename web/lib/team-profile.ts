/**
 * A team member's page content: the three jsonb lists, read safely.
 *
 * `hobbies`, `links` and `photos` are jsonb (migration 0010), so what comes
 * back is whatever is in the row — including from a version of the admin that
 * no longer exists, or a hand-edited row. Everything is therefore parsed here
 * rather than trusted: anything of the wrong shape is dropped, and the page
 * renders the sections that are left instead of failing.
 *
 * The same functions are used when saving (lib/mutations.ts), so a row can only
 * ever hold what this file admits — one definition of the shape, both ways.
 *
 * Imported by both the server pages and the admin form: nothing server-only.
 */

import type { Json } from "@/types/database";

export type Hobby = { title: string; body: string; image_url: string | null };
export type MemberLink = { label: string; url: string };
export type Photo = { url: string; caption: string };

/** How many of each a person may have. A page, not an archive. */
export const LIMITS = { hobbies: 12, links: 10, photos: 24 } as const;

function asArray(value: Json | null | undefined): Record<string, Json>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Record<string, Json> =>
      typeof item === "object" && item !== null && !Array.isArray(item),
  );
}

function str(value: Json | undefined, max = 2000): string {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

/** A URL we are willing to put in href. Anything else (javascript:, data:) is dropped. */
export function safeUrl(value: Json | undefined): string | null {
  const raw = str(value, 2048);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function hobbies(value: Json | null | undefined): Hobby[] {
  return asArray(value)
    .map((item) => ({
      title: str(item.title, 120),
      body: str(item.body, 1200),
      image_url: safeUrl(item.image_url),
    }))
    .filter((h) => h.title || h.body || h.image_url)
    .slice(0, LIMITS.hobbies);
}

export function links(value: Json | null | undefined): MemberLink[] {
  return asArray(value)
    .map((item) => ({ label: str(item.label, 60), url: safeUrl(item.url) }))
    .filter((l): l is MemberLink => l.url !== null)
    .map((l) => ({ ...l, label: l.label || hostOf(l.url) }))
    .slice(0, LIMITS.links);
}

export function photos(value: Json | null | undefined): Photo[] {
  return asArray(value)
    .map((item) => ({ url: safeUrl(item.url), caption: str(item.caption, 200) }))
    .filter((p): p is Photo => p.url !== null)
    .slice(0, LIMITS.photos);
}

/** "github.com/samsmoak" — what a link says when nobody gave it a label. */
export function hostOf(url: string): string {
  try {
    const { host, pathname } = new URL(url);
    const path = pathname.replace(/\/$/, "");
    return `${host.replace(/^www\./, "")}${path}`.slice(0, 60);
  } catch {
    return url.slice(0, 60);
  }
}

/**
 * Which glyph a link gets. Matched on the host, because the label is free text
 * and "my code" should still show the GitHub mark.
 */
export type LinkKind = "github" | "linkedin" | "x" | "instagram" | "youtube" | "web";

export function linkKind(url: string): LinkKind {
  let host = "";
  try {
    host = new URL(url).host.toLowerCase().replace(/^www\./, "");
  } catch {
    return "web";
  }
  if (host === "github.com" || host.endsWith(".github.com") || host.endsWith("github.io")) return "github";
  if (host === "linkedin.com" || host.endsWith(".linkedin.com")) return "linkedin";
  if (host === "x.com" || host === "twitter.com") return "x";
  if (host === "instagram.com" || host.endsWith(".instagram.com")) return "instagram";
  if (host === "youtube.com" || host.endsWith(".youtube.com") || host === "youtu.be") return "youtube";
  return "web";
}

/** Paragraphs from a textarea: blank lines separate, so the admin needs no editor. */
export function paragraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
}

/**
 * A URL-safe slug from a name. Used to *propose* one in the admin — never to
 * derive a page's address at render time, which would move someone's page the
 * day they are renamed.
 */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}
