import Image from "next/image";
import Link from "next/link";
import type { AlbumCard as AlbumCardData } from "@/lib/queries";
import { galleryPath } from "@/lib/routes";
import { PhotoIcon, PlayIcon } from "./icons";

/**
 * An album in the grid: a mosaic of its first photos, then its name and what is
 * inside. Laid out like a project card so the two pages read as one site.
 */
export function AlbumCard({ album, priority = false }: { album: AlbumCardData; priority?: boolean }) {
  const [first, second, third] = album.preview;
  const lead = first?.url ?? album.cover_image_url;

  return (
    <Link
      href={galleryPath(album.slug)}
      className="group flex h-full flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="relative grid aspect-[4/3] grid-cols-3 grid-rows-2 gap-1 overflow-hidden bg-[var(--surface-2)]">
        <div className={`relative overflow-hidden ${second ? "col-span-2 row-span-2" : "col-span-3 row-span-2"}`}>
          {lead ? (
            <Image src={lead} alt="" fill priority={priority} sizes="(max-width: 768px) 70vw, 25vw"
                   className="object-cover transition-transform duration-700 group-hover:scale-105" />
          ) : (
            <span className="font-display flex h-full items-center justify-center text-5xl text-[var(--muted)]">
              {album.title.charAt(0)}
            </span>
          )}
        </div>
        {second && (
          <div className="relative overflow-hidden">
            <Image src={second.url} alt="" fill sizes="15vw" className="object-cover transition-transform duration-700 group-hover:scale-105" />
          </div>
        )}
        {second && (
          <div className="relative overflow-hidden">
            {third ? (
              <Image src={third.url} alt="" fill sizes="15vw" className="object-cover transition-transform duration-700 group-hover:scale-105" />
            ) : (
              <div className="h-full w-full bg-[var(--surface-2)]" />
            )}
          </div>
        )}
        <span className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-transparent" />
        {album.category && (
          <span className="absolute left-3 top-3 rounded-full bg-white/90 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-neutral-900 shadow-sm backdrop-blur">
            {album.category}
          </span>
        )}
        <span className="absolute bottom-3 left-3 flex items-center gap-3 text-xs font-semibold text-white drop-shadow">
          {album.photoCount > 0 && (
            <span className="inline-flex items-center gap-1.5"><PhotoIcon /> {album.photoCount}</span>
          )}
          {album.videoCount > 0 && (
            <span className="inline-flex items-center gap-1.5"><PlayIcon className="h-3.5 w-3.5" /> {album.videoCount}</span>
          )}
        </span>
      </div>

      <div className="flex flex-1 flex-col p-6">
        {album.date_label && <p className="eyebrow mb-2">{album.date_label}</p>}
        <h2 className="font-display text-xl font-semibold leading-snug transition-colors group-hover:text-[var(--heading)]">
          {album.title}
        </h2>
        {album.summary && (
          <p className="mt-2.5 line-clamp-3 text-sm leading-relaxed text-[var(--muted)]">{album.summary}</p>
        )}
        <span className="mt-auto inline-flex items-center gap-1.5 self-start pt-5 text-sm font-semibold text-[var(--heading)]">
          Open album
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"
               className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </span>
      </div>
    </Link>
  );
}
