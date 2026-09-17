import { SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Link from "next/link";
import { ProductCard } from "@/components/site/ProductCard";
import { PageIntro } from "@/components/site/PageIntro";
import { PRODUCTS } from "@/lib/products";
import { getPageContent } from "@/lib/queries";
import { APPS, HARDWARE, setupPath } from "@/lib/routes";

export const metadata: Metadata = {
  title: "Set up the system",
  description:
    "Setup guides for each piece of CropWatcher: the desktop app that flies the drone, the " +
    "flight agent it bundles, and the dashboard that reads what they record.",
};

/**
 * The setup index: one card per product, each opening its own guide.
 *
 * One long page used to cover all of it, which meant every step had to say
 * which piece it was about. A card each answers "which of these am I setting
 * up" before the first instruction. The wording here is edited at
 * /admin/pages/setup-index; each guide has its own page there too.
 */
export default async function SetupIndexPage() {
  const intro = await getPageContent("setup-index");

  return (
    <main className={`${SITE_CONTAINER} py-14`}>
      <PageIntro content={intro} />

      <div className="mt-10 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {PRODUCTS.map((product) => (
          <ProductCard
            key={product.slug}
            product={product}
            href={setupPath(product.slug)}
            action="Setup guide"
            footer={
              product.platforms.length > 0
                ? `${product.platforms.map((p) => p.os).join(" · ")} download`
                : "No download"
            }
          />
        ))}
      </div>

      <section className="mt-12 grid gap-3 border-t border-[var(--border)] pt-8 text-sm text-[var(--muted)] sm:flex sm:flex-wrap sm:gap-6">
        <p>
          Not sure which part is which?{" "}
          <Link href={HARDWARE} className="underline underline-offset-4">
            Every component, photographed and labelled
          </Link>
          .
        </p>
        <p>
          Just want the installer?{" "}
          <Link href={APPS} className="underline underline-offset-4">
            The downloads are on Apps
          </Link>
          .
        </p>
      </section>
    </main>
  );
}
