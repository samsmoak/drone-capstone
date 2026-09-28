import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import Image from "next/image";
import Link from "next/link";
import { PartCards, StatusTag } from "@/components/site/PartCards";
import { Wordmark } from "@/components/site/Wordmark";
import { getPageContent, getPublishedAlbums } from "@/lib/queries";
import { GALLERY, galleryPath, OPERATOR_HOME, PROJECTS, TEAM } from "@/lib/routes";
import { flag, items, text } from "@/lib/site-content";

export const metadata = {
  title: "DroneDeck — autonomous indoor drone inspection",
  description:
    "An autonomous indoor inspection drone built on a Crazyflie 2.1: it flies a route of " +
    "inspection points, records temperature, pressure and images at each, and flags what " +
    "looks wrong on a dashboard.",
};

/**
 * The landing page. Every word and photo here is edited at /admin/pages/home.
 *
 * Top to bottom: the name and what it is, the numbers that size the project,
 * the six parts it is built from (each card links to that part's write-up),
 * the roadmap sprint by sprint, the planning document itself, the gallery
 * strip, and the team. Every section is left out when its fields are empty,
 * so an edit that clears one never leaves an empty heading behind.
 */
export default async function LandingPage() {
  const home = await getPageContent("home");
  const albums = flag(home, "showGallery") ? (await getPublishedAlbums()).slice(0, 4) : [];
  const hero = text(home, "heroImage");
  const stats = items(home, "stats").filter((s) => text(s, "value"));
  const parts = items(home, "capabilities");
  const roadmap = items(home, "roadmap");
  const planFile = text(home, "planFile");

  return (
    <main className={`${SITE_CONTAINER} py-16 md:py-20`}>
      <section className="grid items-center gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
        <div className={PROSE_COLUMN}>
          <p className="eyebrow text-[var(--heading)]">{text(home, "eyebrow")}</p>
          <h1 className="mt-4">
            <Wordmark size="lg" />
          </h1>
          <p className="font-display mt-5 text-2xl font-semibold leading-snug tracking-tight sm:text-3xl">
            {text(home, "title")}
          </p>
          <p className="mt-4 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">{text(home, "intro")}</p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link href={PROJECTS}
                  className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]">
              {text(home, "primaryCta")}
            </Link>
            <Link href={OPERATOR_HOME}
                  className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 font-medium">
              {text(home, "secondaryCta")}
            </Link>
          </div>
        </div>

        {hero && (
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-white shadow-sm">
            {/* A white well in both themes: the photograph's own background is white. */}
            <Image
              src={hero}
              alt={text(home, "heroImageAlt")}
              fill
              priority
              sizes="(max-width: 1024px) 100vw, 40vw"
              className="object-contain p-4"
            />
          </div>
        )}
      </section>

      {stats.length > 0 && (
        <section aria-label="The project in numbers" className="mt-14">
          <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--border)] sm:grid-cols-4">
            {stats.map((stat, i) => (
              <div key={`${text(stat, "label")}-${i}`} className="bg-[var(--surface)] p-5">
                <dt className="text-sm text-[var(--muted)]">{text(stat, "label")}</dt>
                <dd className="font-display mt-1 text-3xl font-semibold tracking-tight">{text(stat, "value")}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {parts.length > 0 && (
        <section aria-labelledby="parts-heading" className="mt-16">
          {text(home, "capabilitiesTitle") && (
            <div className={PROSE_COLUMN}>
              <h2 id="parts-heading" className="font-display text-3xl font-semibold tracking-tight">
                {text(home, "capabilitiesTitle")}
              </h2>
              {text(home, "capabilitiesIntro") && (
                <p className="mt-3 leading-relaxed text-[var(--muted)]">{text(home, "capabilitiesIntro")}</p>
              )}
            </div>
          )}
          <PartCards parts={parts} className="mt-8" />
          <Link href={PROJECTS} className="mt-6 inline-flex min-h-11 items-center text-sm font-medium text-[var(--heading)] underline-offset-4 hover:underline">
            All six parts, the overview and the design document →
          </Link>
        </section>
      )}

      {roadmap.length > 0 && (
        <section aria-labelledby="roadmap-heading" className="mt-20">
          <div className={PROSE_COLUMN}>
            <h2 id="roadmap-heading" className="font-display text-3xl font-semibold tracking-tight">
              {text(home, "roadmapTitle")}
            </h2>
            {text(home, "roadmapIntro") && (
              <p className="mt-3 leading-relaxed text-[var(--muted)]">{text(home, "roadmapIntro")}</p>
            )}
          </div>
          <ol className="mt-8 grid gap-3">
            {roadmap.map((stage, i) => (
              <li key={`${text(stage, "when")}-${i}`}
                  className="grid gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] md:gap-6">
                <div>
                  <p className="tabular text-sm font-medium">{text(stage, "when")}</p>
                  {text(stage, "status") && <StatusTag status={text(stage, "status")} className="mt-2" />}
                </div>
                <div>
                  <h3 className="font-medium">{text(stage, "title")}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-[var(--muted)]">{text(stage, "body")}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {planFile && (
        <section aria-labelledby="plan-heading"
                 className="mt-16 flex flex-col gap-5 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-6 sm:flex-row sm:items-center sm:justify-between sm:p-8">
          <div className="max-w-2xl">
            <h2 id="plan-heading" className="font-display text-2xl font-semibold tracking-tight">{text(home, "planTitle")}</h2>
            <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{text(home, "planBody")}</p>
          </div>
          <a href={planFile} target="_blank" rel="noopener"
             className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z M14 3v6h6 M9 14h6 M9 17h4" />
            </svg>
            {text(home, "planLinkLabel")}
            <span className="sr-only"> (PDF, opens in a new tab)</span>
          </a>
        </section>
      )}

      {albums.length > 0 && (
        <section className="mt-16">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 className="font-display text-2xl font-semibold tracking-tight">{text(home, "galleryTitle")}</h2>
            <Link href={GALLERY} className="text-sm font-medium text-[var(--heading)] underline-offset-4 hover:underline">
              Every album
            </Link>
          </div>
          <ul className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {albums.map((album) => (
              <li key={album.id}>
                <Link href={galleryPath(album.slug)} className="group block">
                  <div className="relative aspect-[4/3] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-2)]">
                    {album.cover_image_url && (
                      <Image
                        src={album.cover_image_url}
                        alt=""
                        fill
                        sizes="(max-width: 1024px) 50vw, 25vw"
                        className="object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                      />
                    )}
                  </div>
                  <p className="mt-2 text-sm font-medium group-hover:text-[var(--heading)]">{album.title}</p>
                  {album.category && <p className="text-xs text-[var(--muted)]">{album.category}</p>}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-16 border-t border-[var(--border)] pt-8">
        <p className="text-sm text-[var(--muted)]">
          {text(home, "teamLine")}{" "}
          <Link href={TEAM} className="underline underline-offset-4">{text(home, "teamLinkLabel")}</Link>.
        </p>
      </section>
    </main>
  );
}
