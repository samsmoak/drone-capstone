/**
 * Installer downloads for /setup.
 *
 * The installers live in the public `installers` bucket at stable paths, which
 * CI overwrites on every release — so this never needs a redeploy for a new
 * version. What it does need is to know whether a file is there yet: a button
 * that downloads a 404 page is worse than one that says "coming soon".
 *
 * So each object is checked with a HEAD request, cached for an hour. A failed
 * check falls back to "coming soon" rather than to a broken link.
 */

const PLATFORMS = [
  {
    // macos-latest runners are Apple silicon; an Intel build is not produced.
    label: "Download for macOS",
    note: "Apple silicon",
    object: "latest/CropWatcher-macos.dmg",
  },
  {
    label: "Download for Windows",
    note: "64-bit",
    object: "latest/CropWatcher-windows.exe",
  },
] as const;

function installerUrl(object: string): string | null {
  const base = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!base || base === "https://your-project-ref.supabase.co") return null;
  return `${base}/storage/v1/object/public/installers/${object}`;
}

async function isPublished(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, {
      method: "HEAD",
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(3000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function DownloadButtons() {
  const platforms = await Promise.all(
    PLATFORMS.map(async (platform) => {
      const url = installerUrl(platform.object);
      return { ...platform, url: url && (await isPublished(url)) ? url : null };
    }),
  );

  return (
    <div className="mt-4 flex flex-wrap gap-3">
      {platforms.map((platform) =>
        platform.url ? (
          <a
            key={platform.object}
            href={platform.url}
            download
            className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--primary)] px-5 text-sm font-medium text-[var(--on-primary)]"
          >
            {platform.label}
            <span className="font-normal opacity-90">({platform.note})</span>
          </a>
        ) : (
          <span
            key={platform.object}
            className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 text-sm text-[var(--muted)]"
          >
            {platform.label} — coming soon
          </span>
        ),
      )}
    </div>
  );
}
