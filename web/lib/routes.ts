/** Route constants, so a path is never spelled twice. */

export const HOME = "/";
export const PROJECTS = "/projects";
export const projectPath = (slug: string) => `${PROJECTS}/${encodeURIComponent(slug)}`;
export const SETUP = "/setup";
export const HARDWARE = "/setup/hardware";
export const GALLERY = "/gallery";
export const TEAM = "/team";

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
export const adminProjectPath = (id: string) => `${ADMIN_PROJECTS}/${id}`;

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
  { href: ADMIN, label: "Admin" },
] as const;

export const ADMIN_NAV = [
  { href: ADMIN_PROJECTS, label: "Projects" },
  { href: ADMIN_TEAM, label: "Team" },
] as const;
