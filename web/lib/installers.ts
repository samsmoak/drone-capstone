import "server-only";

/**
 * The app bundles this site hands out, and what CI says about them.
 *
 * The files live in the public `installers` bucket (migration 0005) at stable
 * paths — `latest/CropWatcher-macos.dmg` — which the desktop-release workflow
 * overwrites on every build. Stable paths mean a new build needs no redeploy
 * here, and no database row: the bucket *is* the list.
 *
 * Beside them CI writes `latest/manifest.json`, so the page can say which
 * version and when, instead of offering two unlabelled files:
 *
 *   { "version": "0.1.0", "commit": "abc1234", "built_at": "2026-09-17T…Z",
 *     "bundles": { "CropWatcher-macos.dmg": { "bytes": 12345678 }, … } }
 *
 * Everything degrades: no manifest → the buttons still work, without the
 * version; no file → "coming soon" rather than a link to a 404. A build that
 * has never run must not produce a broken download.
 *
 * Grouped by app rather than a flat list of files, because there will be a
 * second one (the agent on its own, for a Linux teammate) and "which app is
 * this" should not have to be read out of a filename.
 */

export type Platform = {
  /** The object path in the bucket. */
  object: string;
  os: "macOS" | "Windows";
  /** What the download actually is, for someone deciding whether to click. */
  note: string;
  /** How to get past the OS warning an unsigned build produces. */
  unsigned: string;
};

export type AppBundle = {
  key: string;
  name: string;
  summary: string;
  /** What it does once installed — three lines, not a manual. */
  points: string[];
  platforms: Platform[];
};

export const APPS: AppBundle[] = [
  {
    key: "cropwatcher-desktop",
    name: "CropWatcher desktop app",
    summary:
      "The app that flies the drone. It bundles the flight agent, so the laptop with the " +
      "Crazyradio needs nothing else installed — no Python, no terminal.",
    points: [
      "Pre-flight checks, autonomous missions and manual flight with the keyboard.",
      "Live sensor windows at 10 Hz, and every session recorded to this computer.",
      "Uploads finished flights to this dashboard when it can reach the network.",
    ],
    platforms: [
      {
        object: "latest/CropWatcher-macos.dmg",
        os: "macOS",
        // macos-latest runners are Apple silicon; an Intel build is not produced.
        note: "Apple silicon · macOS 13 or newer",
        unsigned:
          "macOS will say the app is from an unidentified developer. Open it once from " +
          "Finder with Control-click → Open, and it will launch normally afterwards.",
      },
      {
        object: "latest/CropWatcher-windows.exe",
        os: "Windows",
        note: "64-bit · Windows 10 or newer",
        unsigned:
          "Windows SmartScreen will warn about an unrecognised app. Choose More info → " +
          "Run anyway.",
      },
    ],
  },
];

export type BundleFile = {
  url: string | null;
  bytes: number | null;
  /** When the object itself was last written, when the store says. */
  updated: string | null;
};

export type Manifest = {
  version: string | null;
  commit: string | null;
  built_at: string | null;
};

const MANIFEST_OBJECT = "latest/manifest.json";
/** An hour: a release is not urgent, and every visitor would otherwise HEAD the bucket. */
const REVALIDATE = 3600;

export function installerUrl(object: string): string | null {
  const base = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!base || base === "https://your-project-ref.supabase.co") return null;
  return `${base}/storage/v1/object/public/installers/${object}`;
}

/**
 * Is the file there, and how big? A button that downloads a 404 page is worse
 * than one that says "coming soon", so this is checked rather than assumed.
 */
export async function bundleFile(object: string): Promise<BundleFile> {
  const url = installerUrl(object);
  if (!url) return { url: null, bytes: null, updated: null };
  try {
    const response = await fetch(url, {
      method: "HEAD",
      next: { revalidate: REVALIDATE },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return { url: null, bytes: null, updated: null };
    const length = Number(response.headers.get("content-length"));
    return {
      url,
      bytes: Number.isFinite(length) && length > 0 ? length : null,
      updated: response.headers.get("last-modified"),
    };
  } catch {
    return { url: null, bytes: null, updated: null };
  }
}

export async function manifest(): Promise<Manifest | null> {
  const url = installerUrl(MANIFEST_OBJECT);
  if (!url) return null;
  try {
    const response = await fetch(url, {
      next: { revalidate: REVALIDATE },
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    if (typeof data !== "object" || data === null) return null;
    const row = data as Record<string, unknown>;
    const text = (key: string) => (typeof row[key] === "string" ? (row[key] as string) : null);
    return { version: text("version"), commit: text("commit"), built_at: text("built_at") };
  } catch {
    return null;
  }
}

export function formatBytes(bytes: number | null): string | null {
  if (!bytes) return null;
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
}

export function formatDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}
