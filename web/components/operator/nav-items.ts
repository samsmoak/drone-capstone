import {
  ADMIN_GALLERY, ADMIN_PAGES, ADMIN_PROJECTS, ADMIN_TEAM,
  COMPARE, FLIGHTS, LIVE, MANUAL, OPERATOR_HOME, PLAN, SETTINGS, ZONES,
} from "@/lib/routes";

/**
 * The operator view's navigation, in two groups. Icons are 24×24 path data,
 * the shape ../doctor-portfolio's AdminSidebar uses.
 */
export type OperatorNavItem = { href: string; label: string; icon: string };
export type OperatorNavGroup = { label: string; operatorOnly?: boolean; items: OperatorNavItem[] };

export const OPERATOR_GROUPS: OperatorNavGroup[] = [
  {
    label: "Flight data",
    items: [
      { href: OPERATOR_HOME, label: "Dashboard", icon: "M4 5a1 1 0 011-1h5v7H4V5zm0 8h6v7H5a1 1 0 01-1-1v-6zm8-9h4a1 1 0 011 1v4h-5V4zm0 7h5v8a1 1 0 01-1 1h-4v-9z" },
      { href: LIVE, label: "Live", icon: "M12 4a8 8 0 100 16 8 8 0 000-16zm0 4.5a3.5 3.5 0 110 7 3.5 3.5 0 010-7z" },
      { href: FLIGHTS, label: "Flights", icon: "M3 17l6-6 4 4 8-8v4h2V4h-7v2h4l-7 7-4-4-7 7z" },
      { href: ZONES, label: "Zones", icon: "M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z" },
      { href: COMPARE, label: "Compare", icon: "M9 3h2v18H9V3zm4 5h2v13h-2V8zM5 11h2v10H5V11zm12-4h2v14h-2V7z" },
      { href: PLAN, label: "Plan", icon: "M12 2a7 7 0 00-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 00-7-7zm0 9.5A2.5 2.5 0 1112 6a2.5 2.5 0 010 5.5z" },
      { href: MANUAL, label: "Manual", icon: "M7 9h10a4 4 0 014 4v2a4 4 0 01-4 4H7a4 4 0 01-4-4v-2a4 4 0 014-4zm1 3v2H6v1.5h2V17h1.5v-1.5h2V14h-2v-2H8zm8 1a1 1 0 100 2 1 1 0 000-2z" },
      { href: SETTINGS, label: "Settings", icon: "M12 8.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7zm8.4 4.9l1.6 1.2-2 3.4-1.9-.7a7.9 7.9 0 01-1.7 1l-.3 2h-4l-.3-2a7.9 7.9 0 01-1.7-1l-1.9.7-2-3.4 1.6-1.2a8 8 0 010-2L2 9.2l2-3.4 1.9.7a7.9 7.9 0 011.7-1l.3-2h4l.3 2a7.9 7.9 0 011.7 1l1.9-.7 2 3.4-1.6 1.2a8 8 0 010 2z" },
    ],
  },
  {
    label: "Website",
    operatorOnly: true,
    items: [
      { href: ADMIN_PAGES, label: "Pages", icon: "M6 2h9l5 5v15H6a2 2 0 01-2-2V4a2 2 0 012-2zm8 1.5V8h4.5L14 3.5zM8 12v2h8v-2H8zm0 4v2h6v-2H8z" },
      { href: ADMIN_PROJECTS, label: "Projects", icon: "M4 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v9a2 2 0 01-2 2H6a2 2 0 01-2-2V6z" },
      { href: ADMIN_TEAM, label: "Team", icon: "M9 11a4 4 0 100-8 4 4 0 000 8zm8 0a3 3 0 100-6 3 3 0 000 6zM1 20c0-3.3 3.6-6 8-6s8 2.7 8 6v1H1v-1zm17 1v-1c0-1.9-.8-3.6-2.1-4.9 3.5.3 6.1 2.3 6.1 4.9v1h-4z" },
      { href: ADMIN_GALLERY, label: "Gallery", icon: "M4 5h16a1 1 0 011 1v12a1 1 0 01-1 1H4a1 1 0 01-1-1V6a1 1 0 011-1zm1 11.5h14l-4.5-6-3.5 4.5-2.5-3L5 16.5zM8 8a1.5 1.5 0 100 3 1.5 1.5 0 000-3z" },
    ],
  },
];

/** The most specific item matching the path, so /app never claims /app/live. */
export function activeHref(pathname: string, groups: OperatorNavGroup[]): string | undefined {
  return groups
    .flatMap((g) => g.items)
    .filter((i) => pathname === i.href || pathname.startsWith(i.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
}
