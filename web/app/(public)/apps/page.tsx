import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "@/components/site/PageIntro";
import { ProductCard } from "@/components/site/ProductCard";
import { bundleFile, formatBytes, formatDate, manifest } from "@/lib/installers";
import { PRODUCTS } from "@/lib/products";
import { getPageContent } from "@/lib/queries";
import { appPath, SETUP, setupPath } from "@/lib/routes";
import { text } from "@/lib/site-content";

export const metadata: Metadata = {
  title: "Apps",
  description:
    "Download the CropWatcher desktop app for macOS or Windows. Built by CI from the main " +
    "branch, so the download is never behind the code.",
};

/** What the card says instead of a size: how many builds are actually there. */
async function availability(objects: string[]): Promise<string> {
  const files = await Promise.all(objects.map(bundleFile));
  const published = files.filter((f) => f.url);
  if (published.length === 0) return "Building";
  const bytes = published.reduce((sum, f) => sum + (f.bytes ?? 0), 0) / published.length;
  return `${published.length} of ${objects.length} · ${formatBytes(bytes) ?? "—"}`;
}

/**
 * The downloads index: one card per product, each opening its own page.
 *
 * Grouped by product rather than listed as files, because "which app is this"
 * should not have to be read out of a filename — and because the pieces that
 * have nothing to download still belong here, saying so.
 *
 * Wording is edited at /admin/pages/apps; the builds come from CI, not from
 * anything anybody types (docs/features/development/releases.txt).
 */
export default async function AppsPage() {
  const [content, build] = await Promise.all([getPageContent("apps"), manifest()]);
  const built = formatDate(build?.built_at ?? null);

  const cards = await Promise.all(
    PRODUCTS.map(async (product) => ({
      product,
      footer:
        product.platforms.length > 0
          ? await availability(product.platforms.map((p) => p.object))
          : null,
    })),
  );

  return (
    <main className={`${SITE_CONTAINER} py-14`}>
      <PageIntro content={content} />

      {text(content, "note") && (
        <p className={`${PROSE_COLUMN} mt-8 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 leading-relaxed`}>
          {text(content, "note")}
        </p>
      )}

      {(build?.version || built || build?.commit) && (
        <p className="tabular mt-6 text-sm text-[var(--muted)]">
          {[
            build?.version && `Current version ${build.version}`,
            built && `built ${built}`,
            build?.commit && `commit ${build.commit.slice(0, 7)}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}

      <div className="mt-8 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {cards.map(({ product, footer }) => (
          <ProductCard
            key={product.slug}
            product={product}
            href={product.platforms.length > 0 ? appPath(product.slug) : setupPath(product.slug)}
            action={product.platforms.length > 0 ? "Downloads" : "Setup guide"}
            footer={footer ?? product.instead}
          />
        ))}
      </div>

      <section className={`${PROSE_COLUMN} mt-12 border-t border-[var(--border)] pt-8`}>
        <h2 className="font-display text-xl font-semibold tracking-tight">
          {text(content, "unsignedTitle")}
        </h2>
        <p className="mt-3 leading-relaxed text-[var(--muted)]">{text(content, "unsignedIntro")}</p>
        <p className="mt-4 text-sm text-[var(--muted)]">
          Installed it already?{" "}
          <Link href={SETUP} className="underline underline-offset-4">
            The setup guides take it from there
          </Link>
          .
        </p>
      </section>
    </main>
  );
}
