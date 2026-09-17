/** Route constants, so a path is never spelled twice. */

export const HOME = "/";
export const PROJECTS = "/projects";
export const projectPath = (slug: string) => `${PROJECTS}/${encodeURIComponent(slug)}`;
export const SETUP = "/setup";
/** One product's guide. "hardware" is a real page under /setup, never a slug. */
export const setupPath = (slug: string) => `${SETUP}/${encodeURIComponent(slug)}`;
export const HARDWARE = "/setup/hardware";
export const GALLERY = "/gallery";
export const galleryPath = (slug: string) => `${GALLERY}/${encodeURIComponent(slug)}`;
export const TEAM = "/team";
export const memberPath = (slug: string) => `${TEAM}/${encodeURIComponent(slug)}`;
export const APPS = "/apps";
export const appPath = (slug: string) => `${APPS}/${encodeURIComponent(slug)}`;

export const LOGIN = "/login";
export const AUTH_CALLBACK = "/auth/callback";

export const OPERATOR_HOME = "/app";
export const LIVE = "/app/live";
export const FLIGHTS = "/app/flights";
export const COMPARE = "/app/compare";
export const ZONES = "/app/zones";
export const PLAN = "/app/plan";
export const MANUAL = "/app/manual";
export const SETTINGS = "/app/settings";

export const ADMIN = "/admin";
export const ADMIN_PROJECTS = "/admin/projects";
export const ADMIN_TEAM = "/admin/team";
export const ADMIN_GALLERY = "/admin/gallery";
export const ADMIN_PAGES = "/admin/pages";
export const adminPagePath = (key: string) => `${ADMIN_PAGES}/${key}`;
export const adminAlbumPath = (id: string) => `${ADMIN_GALLERY}/${id}`;
export const adminProjectPath = (id: string) => `${ADMIN_PROJECTS}/${id}`;

/**
 * Where to send someone after signing in, from a `next` parameter.
 *
 * Only a same-site path is accepted. `//evil.example` and `https://…` are
 * refused, or a crafted sign-in link would hand a fresh session's user to
 * another site (an open redirect).
 */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return null;
  return next;
}

/** Everything under these needs a session. */
const PROTECTED_PREFIXES = ["/app", "/admin"] as const;

export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/"),
  );
}

export const PUBLIC_NAV = [
  { href: HOME, label: "Overview" },
  { href: PROJECTS, label: "Projects" },
  { href: SETUP, label: "Set Up" },
  { href: APPS, label: "Apps" },
  { href: GALLERY, label: "Gallery" },
  { href: TEAM, label: "Team" },
] as const;

export const OPERATOR_NAV = [
  { href: OPERATOR_HOME, label: "Dashboard" },
  { href: LIVE, label: "Live" },
  { href: FLIGHTS, label: "Flights" },
  { href: ZONES, label: "Zones" },
  { href: COMPARE, label: "Compare" },
  { href: PLAN, label: "Plan" },
  { href: MANUAL, label: "Manual" },
  { href: SETTINGS, label: "Settings" },
] as const;

export const ADMIN_NAV = [
  { href: ADMIN_PAGES, label: "Pages" },
  { href: ADMIN_PROJECTS, label: "Projects" },
  { href: ADMIN_TEAM, label: "Team" },
  { href: ADMIN_GALLERY, label: "Gallery" },
] as const;
