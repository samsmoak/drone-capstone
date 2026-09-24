"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import type { SessionFrame } from "@/lib/queries";
import { PhotoViewer, type ViewerPhoto } from "@/components/media/PhotoViewer";

/**
 * A session's camera frames: one large at a time with previous / next, a strip
 * of every frame to jump to, "View all" for the whole set as a grid, and a
 * click on any frame for full screen with zoom (the shared PhotoViewer).
 *
 * The frames are the drone's AI-deck camera, recorded to disk on the laptop
 * during the session and uploaded two a second to the private flight-frames
 * bucket (backend/agent/cropwatcher/camera/recording.py). Each carries its time
 * in the session and the drone's position when it was taken.
 */

function clock(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds)) return null;
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function describe(frame: SessionFrame): string {
  const at = clock(frame.t_s);
  const where = frame.x_m !== null && frame.y_m !== null && frame.z_m !== null
    ? `x ${frame.x_m.toFixed(2)} · y ${frame.y_m.toFixed(2)} · z ${frame.z_m.toFixed(2)} m`
    : null;
  return [`Frame ${frame.seq}`, at, where].filter(Boolean).join(" · ");
}

export function FrameGallery({ frames }: { frames: SessionFrame[] }) {
  const [at, setAt] = useState(0);
  const [all, setAll] = useState(false);
  const [viewing, setViewing] = useState<number | null>(null);
  const openedFrom = useRef<HTMLElement | null>(null);

  if (frames.length === 0) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No camera frames for this session. Frames are recorded while a session runs with the
        drone&apos;s camera connected, and upload two a second.
      </p>
    );
  }

  const count = frames.length;
  const current = frames[at];
  const photos: ViewerPhoto[] = frames.map((f) => ({
    src: f.url, alt: `Camera frame ${f.seq}`, caption: describe(f), unoptimized: true,
  }));
  const open = (i: number, from: HTMLElement) => { openedFrom.current = from; setViewing(i); };
  const step = (delta: number) => setAt((i) => (i + delta + count) % count);

  const arrow = "flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-white hover:bg-black/75 focus:outline-none focus-visible:ring-2 focus-visible:ring-white";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <span className="font-semibold">{count}</span> frame{count === 1 ? "" : "s"}
          <span className="text-[var(--muted)]"> · two a second, from the drone&apos;s camera</span>
        </p>
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-pressed={all}
          className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-medium hover:bg-[var(--surface-2)]"
        >
          {all ? "Show one at a time" : "View all"}
        </button>
      </div>

      {all ? (
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          {frames.map((f, i) => (
            <li key={f.seq}>
              <button
                type="button"
                onClick={(e) => open(i, e.currentTarget)}
                aria-label={`View ${describe(f)} full screen`}
                className="group relative block aspect-[4/3] w-full cursor-zoom-in overflow-hidden rounded-lg bg-black ring-1 ring-[var(--border)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
              >
                <Image src={f.url} alt="" fill unoptimized sizes="16vw"
                       className="object-contain transition-transform duration-300 group-hover:scale-105" />
                <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white">
                  {f.seq}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <>
          {/* The carousel: one frame, large, never cropped. */}
          <figure>
            <div className="relative aspect-[4/3] w-full max-w-3xl overflow-hidden rounded-xl bg-black">
              <button
                type="button"
                onClick={(e) => open(at, e.currentTarget)}
                aria-label={`View ${describe(current)} full screen`}
                className="absolute inset-0 cursor-zoom-in focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
              >
                <Image src={current.url} alt={`Camera frame ${current.seq}`} fill unoptimized
                       sizes="(max-width: 768px) 100vw, 768px" className="object-contain" />
              </button>
              {count > 1 && (
                <>
                  <button type="button" aria-label="Previous frame" onClick={() => step(-1)}
                          className={`absolute left-3 top-1/2 -translate-y-1/2 ${arrow}`}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M15 6l-6 6 6 6" /></svg>
                  </button>
                  <button type="button" aria-label="Next frame" onClick={() => step(1)}
                          className={`absolute right-3 top-1/2 -translate-y-1/2 ${arrow}`}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true"><path strokeLinecap="round" strokeLinejoin="round" d="M9 6l6 6-6 6" /></svg>
                  </button>
                </>
              )}
              <span className="absolute right-3 top-3 rounded bg-black/60 px-2 py-1 font-mono text-xs text-white">
                {at + 1} / {count}
              </span>
            </div>
            <figcaption className="mt-2 font-mono text-xs text-[var(--muted)]">{describe(current)}</figcaption>
          </figure>

          {/* Every frame, small — jump anywhere without paging. */}
          {count > 1 && (
            <ol className="flex gap-2 overflow-x-auto pb-2" aria-label="All frames">
              {frames.map((f, i) => (
                <li key={f.seq} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => setAt(i)}
                    aria-label={describe(f)}
                    aria-current={i === at ? "true" : undefined}
                    className={`relative block h-14 w-[4.7rem] overflow-hidden rounded-md bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] ${
                      i === at ? "ring-2 ring-[var(--primary)]" : "opacity-70 ring-1 ring-[var(--border)] hover:opacity-100"
                    }`}
                  >
                    <Image src={f.url} alt="" fill unoptimized sizes="76px" className="object-contain" />
                  </button>
                </li>
              ))}
            </ol>
          )}
        </>
      )}

      <PhotoViewer photos={photos} index={viewing} onIndex={setViewing} restoreFocusTo={openedFrom} />
    </div>
  );
}
