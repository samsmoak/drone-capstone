import Link from "next/link";
import { bundleFile, formatBytes } from "@/lib/installers";
import type { Product } from "@/lib/products";
import { appPath } from "@/lib/routes";

/**
 * One product's downloads, inside its setup guide.
 *
 * The full listing — sizes, build dates, the unsigned-build instructions — is
 * /apps/<slug>. This is the short form for someone already following the steps,
 * so it shows the buttons and points there.
 *
 * Whether each file exists is checked, not assumed: see lib/installers.ts.
 */
export async function DownloadButtons({ product }: { product: Product }) {
  if (product.platforms.length === 0) return null;

  const platforms = await Promise.all(
    product.platforms.map(async (platform) => ({ ...platform, file: await bundleFile(platform.object) })),
  );

  return (
    <div className="mt-4 grid gap-3">
      <div className="flex flex-wrap gap-3">
        {platforms.map((platform) =>
          platform.file.url ? (
            <a
              key={platform.object}
              href={platform.file.url}
              download
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--primary)] px-5 text-sm font-medium text-[var(--on-primary)]"
            >
              Download for {platform.os}
              <span className="font-normal opacity-90">
                ({[platform.note, formatBytes(platform.file.bytes)].filter(Boolean).join(" · ")})
              </span>
            </a>
          ) : (
            <span
              key={platform.object}
              className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 text-sm text-[var(--muted)]"
            >
              Download for {platform.os} — coming soon
            </span>
          ),
        )}
      </div>
      <p className="text-sm text-[var(--muted)]">
        <Link href={appPath(product.slug)} className="underline underline-offset-4">
          All downloads, with what to do about the security warning
        </Link>
      </p>
    </div>
  );
}
