import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import Image from "next/image";
import Link from "next/link";
import { getPageContent, getPublishedAlbums } from "@/lib/queries";
import { GALLERY, galleryPath, OPERATOR_HOME, PROJECTS, TEAM } from "@/lib/routes";
import { flag, items, text } from "@/lib/site-content";

export const metadata = {
  title: "CropWatcher — autonomous crop-health monitoring",
  description:
    "An indoor greenhouse scouting system built on a Crazyflie 2.1: autonomous flight, " +
    "position-tagged environmental data, and zone-level crop-health estimates.",
};

/**
 * The landing page. Every word and photo here is edited at /admin/pages/home.
 *
 * The photos are the project's own: the hero and the capability cards take
 * pictures chosen in the admin (defaulting to the kit photos in /public), and
 * the strip at the bottom is the real gallery — album covers, straight from the
 * table, so it fills itself as albums are added and never shows a placeholder
 * for an album that is not there.
 */
export default async function LandingPage() {
  const home = await getPageContent("home");
  const albums = flag(home, "showGallery") ? (await getPublishedAlbums()).slice(0, 4) : [];
  const hero = text(home, "heroImage");

  return (
    <main className={`${SITE_CONTAINER} py-16 md:py-20`}>
      <section className="grid items-center gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
        <div className={PROSE_COLUMN}>
          <p className="eyebrow text-[var(--heading)]">{text(home, "eyebrow")}</p>
          <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">{text(home, "title")}</h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">{text(home, "intro")}</p>

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
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] shadow-sm">
            <Image
              src={hero}
              alt={text(home, "heroImageAlt")}
              fill
              priority
              sizes="(max-width: 1024px) 100vw, 40vw"
              className="object-cover"
            />
          </div>
        )}
      </section>

      <section className="mt-16 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items(home, "capabilities").map((item, i) => {
          const image = text(item, "image");
          return (
            <article key={`${text(item, "title")}-${i}`}
                     className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
              {image && (
                <div className="relative aspect-[16/10] bg-[var(--surface-2)]">
                  <Image src={image} alt="" fill sizes="(max-width: 640px) 100vw, 25vw" className="object-cover" />
                </div>
              )}
              <div className="p-6">
                <h2 className="font-display text-lg font-semibold">{text(item, "title")}</h2>
                <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{text(item, "body")}</p>
              </div>
            </article>
          );
        })}
      </section>

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
