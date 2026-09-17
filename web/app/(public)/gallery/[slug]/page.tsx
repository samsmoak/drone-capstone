import { SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AlbumCard } from "@/components/gallery/AlbumCard";
import { AlbumMedia } from "@/components/gallery/AlbumMedia";
import { PhotoIcon, PlayIcon } from "@/components/gallery/icons";
import { getPublishedAlbumBySlug, getPublishedAlbums } from "@/lib/queries";
import { GALLERY } from "@/lib/routes";

export async function generateMetadata({ params }: PageProps<"/gallery/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const album = await getPublishedAlbumBySlug(slug).catch(() => null);
  if (!album) return { title: "Album not found" };
  return { title: album.title, description: album.summary || undefined };
}

export default async function AlbumPage({ params }: PageProps<"/gallery/[slug]">) {
  const { slug } = await params;
  const [album, all] = await Promise.all([getPublishedAlbumBySlug(slug), getPublishedAlbums()]);
  if (!album) notFound();

  const photoCount = album.items.filter((i) => i.kind === "image").length;
  const videoCount = album.items.length - photoCount;
  const others = all.filter((a) => a.id !== album.id).slice(0, 3);

  return (
    <main className={`${SITE_CONTAINER} py-10 md:py-14`}>
      <Link href={GALLERY}
            className="mb-8 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--muted)] transition-colors hover:text-[var(--foreground)]">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        All albums
      </Link>

      <header className="max-w-3xl">
        {album.category && <p className="eyebrow text-[var(--heading)]">{album.category}</p>}
        <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">{album.title}</h1>
        {album.summary && <p className="mt-4 text-lg leading-relaxed text-[var(--muted)]">{album.summary}</p>}
        <p className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-[var(--muted)]">
          {album.date_label && <span className="font-medium text-[var(--foreground)]">{album.date_label}</span>}
          {photoCount > 0 && <span className="inline-flex items-center gap-1.5"><PhotoIcon /> {photoCount} photos</span>}
          {videoCount > 0 && <span className="inline-flex items-center gap-1.5"><PlayIcon className="h-3.5 w-3.5" /> {videoCount} videos</span>}
        </p>
      </header>

      {album.items.length === 0 ? (
        <div className="mt-12 rounded-xl border border-dashed border-[var(--border)] p-16 text-center">
          <p className="text-[var(--muted)]">This album is empty for now.</p>
        </div>
      ) : (
        <AlbumMedia items={album.items} />
      )}

      {others.length > 0 && (
        <section aria-labelledby="more-heading" className="mt-20 border-t border-[var(--border)] pt-12">
          <h2 id="more-heading" className="font-display text-2xl font-semibold">More albums</h2>
          <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {others.map((a) => <AlbumCard key={a.id} album={a} />)}
          </div>
        </section>
      )}
    </main>
  );
}
