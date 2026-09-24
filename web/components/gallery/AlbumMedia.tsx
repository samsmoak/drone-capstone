"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import type { GalleryItemRow } from "@/lib/queries";
import { PhotoViewer } from "@/components/media/PhotoViewer";
import { VideoEmbed } from "./VideoEmbed";

/**
 * An album's contents: its videos, then its photos in a masonry layout at their
 * real aspect ratio, each opening full screen.
 *
 * The full-screen viewer is the shared one (components/media/PhotoViewer.tsx,
 * adapted from ../doctor-portfolio's Lightbox) — a flight's camera frames use
 * the same, so the two cannot drift.
 */
export function AlbumMedia({ items }: { items: GalleryItemRow[] }) {
  const videos = items.filter((i) => i.kind === "video");
  const photos = items.filter((i) => i.kind === "image");
  const [index, setIndex] = useState<number | null>(null);
  const openedFrom = useRef<HTMLElement | null>(null);

  return (
    <>
      {videos.length > 0 && (
        <section aria-labelledby="videos-heading" className="mt-10">
          {/* Section names only help when an album has both kinds. */}
          <h2 id="videos-heading" className={photos.length > 0 ? "eyebrow mb-5" : "sr-only"}>Videos</h2>
          <div className="grid gap-6 md:grid-cols-2">
            {videos.map((v) => (
              <figure key={v.id}>
                <VideoEmbed url={v.url} title={v.caption || "Video"} />
                {(v.caption || v.credit) && (
                  <figcaption className="mt-3 text-sm leading-snug">
                    {v.caption}
                    {v.credit && <span className="block text-xs text-[var(--muted)]">{v.credit}</span>}
                  </figcaption>
                )}
              </figure>
            ))}
          </div>
        </section>
      )}

      {photos.length > 0 && (
        <section aria-labelledby="photos-heading" className="mt-12">
          {videos.length > 0 && <h2 id="photos-heading" className="eyebrow mb-5">Photos</h2>}
          <div className="columns-1 gap-5 sm:columns-2 lg:columns-3">
            {photos.map((photo, i) => (
              <figure key={photo.id} className="mb-5 break-inside-avoid">
                <button
                  type="button"
                  onClick={(e) => { openedFrom.current = e.currentTarget; setIndex(i); }}
                  aria-label={photo.caption ? `View “${photo.caption}” full screen` : "View photo full screen"}
                  className="group block w-full cursor-zoom-in overflow-hidden rounded-xl bg-[var(--surface-2)] ring-1 ring-[var(--border)]"
                >
                  <Image
                    src={photo.url}
                    alt={photo.caption || "Photo"}
                    width={photo.width ?? 1600}
                    height={photo.height ?? 1200}
                    sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
                    className="h-auto w-full transition-transform duration-500 group-hover:scale-[1.03]"
                  />
                </button>
                {(photo.caption || photo.credit) && (
                  <figcaption className="mt-2 text-sm leading-snug">
                    {photo.caption}
                    {photo.credit && <span className="block text-xs text-[var(--muted)]">{photo.credit}</span>}
                  </figcaption>
                )}
              </figure>
            ))}
          </div>
        </section>
      )}

      <PhotoViewer
        photos={photos.map((p) => ({
          src: p.url,
          alt: p.caption || "Photo",
          caption: [p.caption, p.credit].filter(Boolean).join(" · ") || undefined,
        }))}
        index={index}
        onIndex={setIndex}
        restoreFocusTo={openedFrom}
      />
    </>
  );
}
