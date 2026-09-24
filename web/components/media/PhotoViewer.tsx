"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type PointerEvent, type RefObject, type WheelEvent } from "react";

/**
 * The full-screen photo viewer — one component, used by the gallery albums and
 * by a flight's camera frames.
 *
 * Adapted from ../doctor-portfolio/components/media/Lightbox.tsx (and extracted
 * from components/gallery/AlbumMedia.tsx, which had its own copy): Escape and a
 * backdrop click close it, the arrow keys page through the set, the page behind
 * stops scrolling, and focus returns to the thumbnail it came from.
 *
 * ZOOM, which neither of those had: + and − (or the wheel, or a double-click)
 * zoom in up to 4×, and a zoomed photo is dragged to look around it. A drone
 * frame is 324×244 — at full screen the detail an operator is looking for is a
 * leaf, not the whole frame. Paging resets the zoom.
 */

export type ViewerPhoto = {
  src: string;
  alt: string;
  /** A line under the photo — a caption, or a frame's time and position. */
  caption?: string;
  /** Signed or otherwise short-lived URLs: skip the image optimiser. */
  unoptimized?: boolean;
};

const MAX_ZOOM = 4;
const STEP = 1.5;

export function PhotoViewer({ photos, index, onIndex, restoreFocusTo }: {
  photos: ViewerPhoto[];
  /** The photo showing, or null when the viewer is closed. */
  index: number | null;
  onIndex: (index: number | null) => void;
  /** Where focus goes back to on close — a ref, read when it closes. */
  restoreFocusTo?: RefObject<HTMLElement | null>;
}) {
  // Zoom and pan belong to ONE photo: stored with the index they were set on,
  // so paging to another photo shows it whole without an effect to reset them.
  const [view, setView] = useState({ at: index, zoom: 1, x: 0, y: 0 });
  const own = view.at === index ? view : { at: index, zoom: 1, x: 0, y: 0 };
  const zoom = own.zoom;
  const pan = { x: own.x, y: own.y };
  const setZoom = (next: number | ((z: number) => number)) =>
    setView((v) => {
      const base = v.at === index ? v : { at: index, zoom: 1, x: 0, y: 0 };
      const z = typeof next === "function" ? next(base.zoom) : next;
      return z <= 1 ? { at: index, zoom: 1, x: 0, y: 0 } : { ...base, zoom: z };
    });
  const setPan = (p: { x: number; y: number }) => setView((v) => ({ ...v, at: index, ...p }));
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const count = photos.length;

  useEffect(() => {
    if (index === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onIndex(null); restoreFocusTo?.current?.focus(); }
      if (e.key === "ArrowRight") onIndex((index + 1) % count);
      if (e.key === "ArrowLeft") onIndex((index - 1 + count) % count);
      if (e.key === "+" || e.key === "=") setZoom((z) => Math.min(MAX_ZOOM, z * STEP));
      if (e.key === "-") setZoom((z) => Math.max(1, z / STEP));
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
    // setZoom is recreated each render; the key handler only needs the latest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, count, onIndex, restoreFocusTo]);

  if (index === null || !photos[index]) return null;
  const current = photos[index];
  const close = () => { onIndex(null); restoreFocusTo?.current?.focus(); };
  const zoomTo = (z: number) => setZoom(Math.min(MAX_ZOOM, Math.max(1, z)));

  const onWheel = (e: WheelEvent) => zoomTo(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
  const onPointerDown = (e: PointerEvent) => {
    if (zoom === 1) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
  };
  const onPointerMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    setPan({ x: d.px + (e.clientX - d.x) / zoom, y: d.py + (e.clientY - d.y) / zoom });
  };
  const onPointerUp = () => { drag.current = null; };

  const round = "flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={current.alt || "Photo viewer"}
      onClick={close}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/90 p-4 backdrop-blur-sm sm:p-8"
    >
      <div className="absolute right-4 top-4 z-10 flex gap-2" onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={() => zoomTo(zoom / STEP)} disabled={zoom <= 1}
                aria-label="Zoom out" className={`${round} disabled:opacity-40`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" d="M6 12h12" /></svg>
        </button>
        <button type="button" onClick={() => zoomTo(zoom * STEP)} disabled={zoom >= MAX_ZOOM}
                aria-label="Zoom in" className={`${round} disabled:opacity-40`}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" d="M12 6v12M6 12h12" /></svg>
        </button>
        <button ref={closeButton} type="button" onClick={close} aria-label="Close photo viewer" className={round}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>

      {count > 1 && (
        <>
          <button type="button" aria-label="Previous photo"
                  onClick={(e) => { e.stopPropagation(); onIndex((index - 1 + count) % count); }}
                  className={`absolute left-4 top-1/2 z-10 -translate-y-1/2 ${round}`}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M15 6l-6 6 6 6" /></svg>
          </button>
          <button type="button" aria-label="Next photo"
                  onClick={(e) => { e.stopPropagation(); onIndex((index + 1) % count); }}
                  className={`absolute right-4 top-1/2 z-10 -translate-y-1/2 ${round}`}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M9 6l6 6-6 6" /></svg>
          </button>
        </>
      )}

      <figure className="flex max-h-full w-full max-w-6xl flex-col items-center" onClick={(e) => e.stopPropagation()}>
        <div
          className={`relative h-[80vh] w-full overflow-hidden ${zoom > 1 ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in"}`}
          onWheel={onWheel}
          onDoubleClick={() => zoomTo(zoom > 1 ? 1 : 2)}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <div
            className="absolute inset-0 transition-transform duration-75 motion-reduce:transition-none"
            style={{ transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)` }}
          >
            <Image src={current.src} alt={current.alt || "Photo"} fill sizes="100vw" priority
                   unoptimized={current.unoptimized} draggable={false}
                   className="select-none object-contain" />
          </div>
        </div>
        <figcaption className="mt-3 text-center text-sm text-white/80">
          {current.caption}
          <span className="ml-3 font-mono text-xs text-white/50">
            {index + 1} / {count}{zoom > 1 ? ` · ${zoom.toFixed(1)}×` : ""}
          </span>
        </figcaption>
      </figure>
    </div>
  );
}
