"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type { GalleryItemRow } from "@/lib/queries";
import { VideoEmbed } from "./VideoEmbed";

/**
 * An album's contents: its videos, then its photos in a masonry layout at their
 * real aspect ratio, each opening full screen.
 *
 * The viewer is adapted from ../doctor-portfolio/components/media/Lightbox.tsx:
 * Escape and a backdrop click close it, the arrow keys page through the album,
 * the page behind stops scrolling, and focus returns to the photo it came from.
 */
export function AlbumMedia({ items }: { items: GalleryItemRow[] }) {
  const videos = items.filter((i) => i.kind === "video");
  const photos = items.filter((i) => i.kind === "image");
  const [index, setIndex] = useState<number | null>(null);
  const openedFrom = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Not memoised by hand: the React Compiler does it, and a manual useCallback
  // here defeats its optimisation (react-hooks/preserve-manual-memoization).
  function close() {
    setIndex(null);
    openedFrom.current?.focus();
  }

  useEffect(() => {
    if (index === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIndex(null);
        openedFrom.current?.focus();
      }
      if (e.key === "ArrowRight") setIndex((i) => (i === null ? i : (i + 1) % photos.length));
      if (e.key === "ArrowLeft") setIndex((i) => (i === null ? i : (i - 1 + photos.length) % photos.length));
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [index, photos.length]);

  const current = index === null ? null : photos[index];

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

      {current && index !== null && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={current.caption || "Photo viewer"}
          onClick={close}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/90 p-4 backdrop-blur-sm sm:p-8"
        >
          <button ref={closeButton} type="button" onClick={close} aria-label="Close photo viewer"
                  className="absolute right-4 top-4 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true">
              <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
          {photos.length > 1 && (
            <>
              <button type="button" aria-label="Previous photo"
                      onClick={(e) => { e.stopPropagation(); setIndex((index - 1 + photos.length) % photos.length); }}
                      className="absolute left-4 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M15 6l-6 6 6 6" /></svg>
              </button>
              <button type="button" aria-label="Next photo"
                      onClick={(e) => { e.stopPropagation(); setIndex((index + 1) % photos.length); }}
                      className="absolute right-4 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M9 6l6 6-6 6" /></svg>
              </button>
            </>
          )}
          <figure className="flex max-h-full w-full max-w-6xl flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <div className="relative h-[80vh] w-full">
              <Image src={current.url} alt={current.caption || "Photo"} fill sizes="100vw" priority className="object-contain" />
            </div>
            <figcaption className="mt-3 text-center text-sm text-white/80">
              {current.caption}
              <span className="ml-3 font-mono text-xs text-white/50">{index + 1} / {photos.length}</span>
              {current.credit && <span className="block text-xs text-white/50">{current.credit}</span>}
            </figcaption>
          </figure>
        </div>
      )}
    </>
  );
}
