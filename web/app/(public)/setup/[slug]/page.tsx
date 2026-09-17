import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AgentStatus } from "@/components/ui/agent-status";
import { DownloadButtons } from "@/components/ui/download-buttons";
import { categoryColor } from "@/lib/categories";
import { PRODUCTS, productBySlug } from "@/lib/products";
import { getPageContent } from "@/lib/queries";
import { appPath, HARDWARE, SETUP, setupPath } from "@/lib/routes";
import { flag, items, strings, text } from "@/lib/site-content";

export function generateStaticParams() {
  return PRODUCTS.map((product) => ({ slug: product.slug }));
}

export async function generateMetadata({ params }: PageProps<"/setup/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const product = productBySlug(slug);
  if (!product) return { title: "Setup guide not found" };
  const content = await getPageContent(product.setupPage);
  return { title: text(content, "title"), description: text(content, "intro") };
}

/**
 * One product's setup guide: numbered steps in the reading column, the things
 * that go wrong alongside.
 *
 * This is the page /setup used to be, now once per product — the steps for the
 * desktop app are not the steps for the agent, and one page that tried to be
 * both would start every step with "if you are installing the app…". Every word
 * is edited at /admin/pages/<the product's page key>.
 */
export default async function SetupGuidePage({ params }: PageProps<"/setup/[slug]">) {
  const { slug } = await params;
  const product = productBySlug(slug);
  if (!product) notFound();

  const setup = await getPageContent(product.setupPage);
  const others = PRODUCTS.filter((p) => p.slug !== product.slug);

  return (
    <main className={`${SITE_CONTAINER} py-14`}>
      <Link
        href={SETUP}
        className="mb-8 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        All setup guides
      </Link>

      <header className={PROSE_COLUMN}>
        <p className="eyebrow flex items-center gap-1.5 text-[var(--heading)]">
          <span
            aria-hidden="true"
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: categoryColor(product.category) }}
          />
          {product.name}
        </p>
        <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight">{text(setup, "title")}</h1>
        <p className="mt-3 text-lg text-[var(--muted)]">{text(setup, "intro")}</p>
        <p className="eyebrow mt-4">Runs on · {product.runsOn}</p>
      </header>

      {/* Steps take the reading column; the troubleshooting list rides alongside
          on a wide screen and falls beneath it on a narrow one. */}
      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
        <div>
          {product.slug === "desktop-app" && <AgentStatus />}
          <ol className="mt-10 space-y-10">
            {items(setup, "steps").map((step, i) => {
              const bullets = strings(step, "bullets");
              const note = text(step, "note");
              return (
                <li key={`${text(step, "title")}-${i}`} className="flex gap-4 sm:gap-5">
                  <span aria-hidden="true"
                        className="tabular flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-sm font-semibold">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="text-lg font-medium">{text(step, "title")}</h2>
                    <div className="mt-2 space-y-3">
                      {strings(step, "paragraphs").map((para, j) => (
                        <p key={j} className="text-[var(--muted)]">{para}</p>
                      ))}
                      {bullets.length > 0 && (
                        <ul className="space-y-1.5 text-sm">
                          {bullets.map((item, j) => (
                            <li key={j} className="flex gap-2">
                              <span aria-hidden="true" className="text-[var(--muted)]">•</span>
                              <span className="wrap-anywhere">{item}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                      {flag(step, "showDownloads") && <DownloadButtons product={product} />}
                      {note && (
                        <p className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm">{note}</p>
                      )}
                      {flag(step, "linkHardware") && (
                        <p className="text-sm text-[var(--muted)]">
                          Not sure which part is which?{" "}
                          <Link href={HARDWARE} className="underline underline-offset-4">
                            See every component photographed and labelled
                          </Link>.
                        </p>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>

        <div className="grid gap-5 lg:sticky lg:top-8 lg:self-start">
          <section aria-labelledby="trouble-heading">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6">
              <h2 id="trouble-heading" className="font-display text-2xl font-semibold tracking-tight">
                {text(setup, "troubleTitle")}
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{text(setup, "troubleIntro")}</p>
              <div className="mt-5 space-y-3">
                {items(setup, "troubles").map((item, i) => (
                  <details key={`${text(item, "symptom")}-${i}`}
                           className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)]">
                    <summary className="flex min-h-11 cursor-pointer items-center px-4 py-3 text-sm font-medium">
                      {text(item, "symptom")}
                    </summary>
                    <div className="border-t border-[var(--border)] px-4 py-3">
                      <p className="text-sm"><span className="text-[var(--muted)]">Usually: </span>{text(item, "cause")}</p>
                      <p className="mt-2 text-sm text-[var(--muted)]">{text(item, "fix")}</p>
                    </div>
                  </details>
                ))}
              </div>
            </div>
          </section>

          <nav aria-label="Other setup guides" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <h2 className="eyebrow mb-3">The other pieces</h2>
            <ul className="grid gap-1.5">
              {others.map((other) => (
                <li key={other.slug} style={{ "--accent": categoryColor(other.category) } as React.CSSProperties}>
                  <Link
                    href={setupPath(other.slug)}
                    className="group relative block overflow-hidden rounded-xl border border-transparent py-2.5 pl-4 pr-3 transition-all duration-200 hover:translate-x-0.5 hover:bg-[color-mix(in_srgb,var(--accent)_8%,var(--surface))]"
                  >
                    <span aria-hidden="true" className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-[var(--accent)]" />
                    <span className="block text-sm font-medium leading-snug">{other.name}</span>
                    <span className="mt-0.5 block text-xs text-[var(--muted)]">{other.runsOn}</span>
                  </Link>
                </li>
              ))}
            </ul>
            {product.platforms.length > 0 && (
              <Link
                href={appPath(product.slug)}
                className="mt-4 inline-block text-sm font-medium text-[var(--heading)] underline-offset-4 hover:underline"
              >
                Downloads for {product.name}
              </Link>
            )}
          </nav>
        </div>
      </div>
    </main>
  );
}
