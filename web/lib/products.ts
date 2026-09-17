/**
 * What this capstone ships, as things you can set up and download.
 *
 * Two pieces, because the radio is a USB dongle (see the repo's CLAUDE.md): the
 * desktop app on the laptop that holds it, and the website that reads what it
 * records. Each has its own setup guide at /setup/<slug>, and the ones with
 * installers have their downloads at /apps/<slug>.
 *
 * The flight agent is not listed. It ships inside the desktop app, so nobody who
 * flies the drone ever sets it up; running it from source is developer work,
 * documented in docs/features/backend/running-from-source.txt.
 *
 * This list is code, not a database row, because every field describes an
 * artifact CI produces — an object path in the bucket is only meaningful next
 * to the workflow that writes it. The *wording* of each setup guide is
 * editable at /admin/pages; what the guide is about is not.
 *
 * No server-only import: the nav, the cards and the pages all read it.
 */

import type { PageKey } from "@/lib/site-content";

export type ProductPlatform = {
  /** The object path in the public `installers` bucket. */
  object: string;
  os: "macOS" | "Windows";
  /** What the download is, for someone deciding whether to click. */
  note: string;
  /** How to get past the warning an unsigned build produces. */
  unsigned: string;
};

export type Product = {
  slug: string;
  name: string;
  /** One line for the card. */
  summary: string;
  /** Colours the cards and the lists, via lib/categories.ts. */
  category: string;
  /** Where it runs — the first thing to know about any of them. */
  runsOn: string;
  /** What it does, three lines, not a manual. */
  points: string[];
  /** The page key holding this guide's editable wording. */
  setupPage: PageKey;
  /** Empty when there is nothing to download. */
  platforms: ProductPlatform[];
  /** Said on the card in place of a size, when there is nothing to download. */
  instead?: string;
  /** Where it lives in the repository. */
  source: string;
};

const GATEKEEPER =
  "macOS will say the app is from an unidentified developer. Open it once from Finder with " +
  "Control-click → Open, and it will launch normally afterwards.";

const SMARTSCREEN =
  "Windows SmartScreen will warn about an unrecognised app. Choose More info → Run anyway.";

export const PRODUCTS: Product[] = [
  {
    slug: "desktop-app",
    name: "CropWatcher desktop app",
    summary:
      "The app that flies the drone. It bundles the flight agent, so the laptop with the " +
      "Crazyradio needs nothing else installed — no Python, no terminal.",
    category: "software",
    runsOn: "The laptop with the Crazyradio plugged in",
    points: [
      "Pre-flight checks, autonomous missions and manual flight from the keyboard.",
      "Live sensor windows at 10 Hz, and every session recorded to that computer.",
      "Uploads finished flights to this dashboard when it can reach the network.",
    ],
    setupPage: "setup",
    source: "desktop/",
    platforms: [
      {
        object: "latest/CropWatcher-macos.dmg",
        os: "macOS",
        // macos-latest runners are Apple silicon; an Intel build is not produced.
        note: "Apple silicon · macOS 13 or newer",
        unsigned: GATEKEEPER,
      },
      {
        object: "latest/CropWatcher-windows.exe",
        os: "Windows",
        note: "64-bit · Windows 10 or newer",
        unsigned: SMARTSCREEN,
      },
    ],
  },
  {
    slug: "dashboard",
    name: "Dashboard and website",
    summary:
      "This site: the public pages and the operator dashboard that reads the flights, zones " +
      "and crop-health estimates the drone records.",
    category: "web",
    runsOn: "Anywhere — it is a website",
    points: [
      "Nothing to install: sign in and open the dashboard.",
      "Run it locally against the same Supabase project when you are changing it.",
      "Deployed from the main branch, with the root directory set to web/.",
    ],
    setupPage: "setup-web",
    source: "web/",
    platforms: [],
    instead: "Nothing to install",
  },
];

export function productBySlug(slug: string): Product | null {
  return PRODUCTS.find((p) => p.slug === slug) ?? null;
}

/** The ones with something to download, for /apps. */
export const DOWNLOADABLE = PRODUCTS.filter((p) => p.platforms.length > 0);
