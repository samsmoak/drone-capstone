import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { categoryColor } from "@/lib/categories";
import { bundleFile, formatBytes, formatDate, manifest } from "@/lib/installers";
import { DOWNLOADABLE, PRODUCTS, productBySlug } from "@/lib/products";
import { getPageContent } from "@/lib/queries";
import { APPS, appPath, setupPath } from "@/lib/routes";
import { text } from "@/lib/site-content";

export function generateStaticParams() {
  return DOWNLOADABLE.map((product) => ({ slug: product.slug }));
}

export async function generateMetadata({ params }: PageProps<"/apps/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const product = productBySlug(slug);
  if (!product) return { title: "App not found" };
  return { title: `Download ${product.name}`, description: product.summary };
}

function AppleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5 shrink-0" aria-hidden="true">
      <path d="M17.05 12.94c-.03-2.7 2.2-3.99 2.3-4.06-1.25-1.83-3.2-2.08-3.9-2.11-1.66-.17-3.24.98-4.08.98-.84 0-2.14-.96-3.52-.93-1.81.03-3.48 1.05-4.41 2.67-1.88 3.26-.48 8.08 1.35 10.72.9 1.29 1.97 2.74 3.38 2.69 1.36-.06 1.87-.88 3.51-.88 1.64 0 2.1.88 3.53.85 1.46-.02 2.38-1.31 3.27-2.61 1.03-1.5 1.46-2.95 1.48-3.03-.03-.01-2.84-1.09-2.87-4.29zM14.4 4.9c.74-.9 1.24-2.15 1.1-3.4-1.07.05-2.36.72-3.13 1.61-.68.79-1.28 2.06-1.12 3.28 1.19.09 2.41-.6 3.15-1.49z" />
    </svg>
  );
}

function WindowsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5 shrink-0" aria-hidden="true">
      <path d="M3 5.6 10.2 4.6v6.9H3V5.6zm0 12.8 7.2 1v-6.8H3v5.8zM11.2 4.4 21 3v8.5h-9.8V4.4zm0 8.1H21V21l-9.8-1.4v-7.1z" />
    </svg>
  );
}

/**
 * One product's downloads: a card per platform, with what each is, how big, when
 * it was built, and what the operating system will say about an unsigned build.
 *
 * Whether a file exists is checked before it is offered — a button that
 * downloads a 404 page is worse than one that says the build has not finished.
 */
export default async function AppDownloadPage({ params }: PageProps<"/apps/[slug]">) {
  const { slug } = await params;
  const product = productBySlug(slug);
  if (!product || product.platforms.length === 0) notFound();

  const [content, build, platforms] = await Promise.all([
    getPageContent("apps"),
    manifest(),
    Promise.all(product.platforms.map(async (p) => ({ ...p, file: await bundleFile(p.object) }))),
  ]);
  const anyPublished = platforms.some((p) => p.file.url);
  const others = PRODUCTS.filter((p) => p.slug !== product.slug);

  return (
    <main className={`${SITE_CONTAINER} py-14`}>
      <Link
        href={APPS}
        className="mb-8 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        All apps
      </Link>

      <header className={PROSE_COLUMN}>
        <p className="eyebrow flex items-center gap-1.5 text-[var(--heading)]">
          <span
            aria-hidden="true"
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: categoryColor(product.category) }}
          />
          Download
        </p>
        <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight">{product.name}</h1>
        <p className="mt-3 text-lg leading-relaxed text-[var(--muted)]">{product.summary}</p>
        <p className="eyebrow mt-4">
          Runs on · {product.runsOn}
          {build?.version ? ` · version ${build.version}` : ""}
        </p>
      </header>

      <ul className="mt-8 grid max-w-2xl gap-2">
        {product.points.map((point) => (
          <li key={point} className="flex gap-2.5 leading-relaxed">
            <span aria-hidden="true" className="text-[var(--heading)]">▸</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>

      <div className="mt-8 grid gap-5 lg:grid-cols-[minmax(0,8fr)_minmax(0,4fr)]">
        <div className="grid gap-4 sm:grid-cols-2">
          {platforms.map((platform) => {
            const size = formatBytes(platform.file.bytes);
            const built = formatDate(platform.file.updated);
            return (
              <article
                key={platform.object}
                className="flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6"
              >
                <h2 className="font-display flex items-center gap-2.5 text-xl font-semibold">
                  {platform.os === "macOS" ? <AppleIcon /> : <WindowsIcon />}
                  {platform.os}
                </h2>
                <p className="mt-1.5 text-sm text-[var(--muted)]">{platform.note}</p>

                <div className="mt-5">
                  {platform.file.url ? (
                    <a
                      href={platform.file.url}
                      download
                      className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--primary)] px-5 text-sm font-medium text-[var(--on-primary)]"
                    >
                      Download{size ? ` · ${size}` : ""}
                    </a>
                  ) : (
                    <span className="inline-flex min-h-11 items-center rounded-lg border border-dashed border-[var(--border)] px-5 text-sm text-[var(--muted)]">
                      Coming soon — the first build has not finished yet
                    </span>
                  )}
                </div>

                {built && <p className="tabular mt-3 text-xs text-[var(--muted)]">Built {built}</p>}
                <p className="mt-3 text-xs leading-relaxed text-[var(--muted)]">{platform.unsigned}</p>
              </article>
            );
          })}
        </div>

        <aside className="grid gap-5">
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <h2 className="font-display text-lg font-semibold tracking-tight">After it downloads</h2>
            <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">
              The setup guide takes it from the installer to a drone in the air — positioning,
              the pre-flight checks, and the first flight.
            </p>
            <Link
              href={setupPath(product.slug)}
              className="mt-4 inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 text-sm font-medium"
            >
              Setup guide →
            </Link>
          </section>

          <nav aria-label="The other pieces" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <h2 className="eyebrow mb-3">The other pieces</h2>
            <ul className="grid gap-1.5">
              {others.map((other) => (
                <li key={other.slug} style={{ "--accent": categoryColor(other.category) } as React.CSSProperties}>
                  <Link
                    href={other.platforms.length > 0 ? appPath(other.slug) : setupPath(other.slug)}
                    className="group relative block overflow-hidden rounded-xl border border-transparent py-2.5 pl-4 pr-3 transition-all duration-200 hover:translate-x-0.5 hover:bg-[color-mix(in_srgb,var(--accent)_8%,var(--surface))]"
                  >
                    <span aria-hidden="true" className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-[var(--accent)]" />
                    <span className="block text-sm font-medium leading-snug">{other.name}</span>
                    <span className="mt-0.5 block text-xs text-[var(--muted)]">
                      {other.platforms.length > 0
                        ? other.platforms.map((p) => p.os).join(" · ")
                        : other.instead}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </aside>
      </div>

      {!anyPublished && (
        <p className="mt-8 max-w-3xl rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 text-sm leading-relaxed text-[var(--muted)]">
          No build has been published yet. One is produced automatically whenever this app changes
          on the main branch, and appears here without anyone redeploying the site.
        </p>
      )}

      {/* Always shown, not only when a build is missing: the download above is
          Apple silicon and 64-bit Windows, and anybody else — an Intel Mac, a
          Linux laptop — needs this sentence rather than a dead end. */}
      <p className="mt-6 max-w-3xl text-sm leading-relaxed text-[var(--muted)]">
        Not the computer you have?{" "}
        <Link href={setupPath(product.slug)} className="underline underline-offset-4">
          Clone the repository and build it yourself
        </Link>
        . Each build is made on the machine it is for — the flight agent is frozen with
        PyInstaller, which does not cross-compile — so your own computer produces the one it
        needs in about ten minutes.
      </p>

      <section className={`${PROSE_COLUMN} mt-12 border-t border-[var(--border)] pt-8`}>
        <h2 className="font-display text-xl font-semibold tracking-tight">{text(content, "unsignedTitle")}</h2>
        <p className="mt-3 leading-relaxed text-[var(--muted)]">{text(content, "unsignedIntro")}</p>
      </section>
    </main>
  );
}
