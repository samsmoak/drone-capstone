"use client";

import Image from "next/image";
import { useRef, useState } from "react";
import type { SessionFrame } from "@/lib/queries";
import { PhotoViewer, type ViewerPhoto } from "@/components/media/PhotoViewer";
import { useHint, type HintText } from "@/components/ui/hint";
import { GROUPS, SEVERITY, groupColor, type Mark } from "@/lib/pipeline";
import { MarkShape } from "@/components/ui/mark-legend";

/**
 * A session's camera frames: one large at a time with previous / next, a strip
 * of every frame to jump to, "View all" for the whole set as a grid, and a
 * click on any frame for full screen with zoom (the shared PhotoViewer).
 *
 * The frames are the drone's AI-deck camera, recorded to disk on the laptop
 * during the session and uploaded two a second to the private flight-frames
 * bucket (backend/agent/cropwatcher/camera/recording.py). Each carries its time
 * in the session and the drone's position when it was taken.
 *
 * With the data pipeline's ENHANCED copies (clahe@1 — contrast for dark
 * frames, nothing drawn that was not there), a switch shows the originals,
 * the enhanced copies, or both side by side. An enhanced image is always
 * labelled as one: it is easier to read, and it is not what the camera saw.
 *
 * FRAMES TAKEN DURING AN ANOMALY ARE MARKED (`marks`, from the findings'
 * evidence frames): a border in the severity's colour and its shape, the
 * meaning on hover, focus or tap, and spelled out under the large frame. A
 * switch narrows the set to those frames. The readings are still the evidence
 * — a marked frame shows what the camera saw then, which may be nothing.
 */

function hintOf(marks: Mark[]): HintText {
  const worst = marks[0];
  return {
    title: marks.length > 1 ? `${worst.title} (and ${marks.length - 1} more)` : worst.title,
    body: `Taken during this anomaly. ${worst.body}`,
    label: `${GROUPS[worst.group].label} · ${SEVERITY[worst.severity].label}`,
    color: groupColor(worst.group),
  };
}

function MarkBadge({ marks, large = false }: { marks: Mark[]; large?: boolean }) {
  const worst = marks[0];
  const sev = SEVERITY[worst.severity];
  return (
    <span className={`pointer-events-none absolute left-1 top-1 inline-flex items-center gap-1 rounded bg-black/75 font-semibold text-white ${
      large ? "px-2 py-1 text-xs" : "px-1 py-0.5 text-[10px]"}`}>
      <MarkShape mark={worst} />
      {large ? `${sev.label} · ${worst.title}` : sev.label}
    </span>
  );
}

type View = "original" | "enhanced" | "both";
const VIEWS: { key: View; label: string }[] = [
  { key: "original", label: "Original" },
  { key: "enhanced", label: "Enhanced" },
  { key: "both", label: "Side by side" },
];

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

export function FrameGallery({ frames: allFrames, enhanced = {}, marks = {} }: {
  frames: SessionFrame[];
  /** Frame seq → a link to its enhanced copy. */
  enhanced?: Record<number, string>;
  /** Frame seq → the anomalies it was taken during, worst first. */
  marks?: Record<number, Mark[]>;
}) {
  const [onlyMarked, setOnlyMarked] = useState(false);
  const hint = useHint();
  const markedCount = allFrames.filter((f) => marks[f.seq]?.length).length;
  const frames = onlyMarked ? allFrames.filter((f) => marks[f.seq]?.length) : allFrames;
  const [view, setView] = useState<View>("original");
  const [at, setAt] = useState(0);
  const [all, setAll] = useState(false);
  const [viewing, setViewing] = useState<number | null>(null);
  const openedFrom = useRef<HTMLElement | null>(null);

  if (allFrames.length === 0) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No camera frames for this session. Frames are recorded while a session runs with the
        drone&apos;s camera connected, and upload two a second.
      </p>
    );
  }

  const count = frames.length;
  const current = frames[Math.min(at, count - 1)];
  const currentMarks = marks[current.seq] ?? [];
  const markStyle = (f: SessionFrame) => {
    const m = marks[f.seq];
    return m?.length ? { boxShadow: `inset 0 0 0 3px ${groupColor(m[0].group)}` } : undefined;
  };
  const hover = (f: SessionFrame) => {
    const m = marks[f.seq];
    if (!m?.length) return {};
    const text = hintOf(m);
    return {
      onMouseEnter: (e: React.MouseEvent<HTMLElement>) => hint.show(text, e.currentTarget),
      onMouseLeave: hint.hide,
      onFocus: (e: React.FocusEvent<HTMLElement>) => hint.show(text, e.currentTarget),
      onBlur: hint.hideNow,
      "aria-describedby": hint.isOpen ? hint.id : undefined,
    };
  };
  const enhancedCount = frames.filter((f) => enhanced[f.seq]).length;
  const showEnhanced = view === "enhanced";
  const src = (f: SessionFrame) => (showEnhanced ? enhanced[f.seq] ?? f.url : f.url);
  const isEnhanced = (f: SessionFrame) => showEnhanced && Boolean(enhanced[f.seq]);
  const photos: ViewerPhoto[] = frames.map((f) => ({
    src: src(f), alt: `Camera frame ${f.seq}${isEnhanced(f) ? ", enhanced" : ""}`,
    caption: `${describe(f)}${isEnhanced(f) ? " · ENHANCED (contrast)" : ""}${
      marks[f.seq]?.length ? ` · ANOMALY: ${marks[f.seq].map((m) => m.title).join("; ")}` : ""}`, unoptimized: true,
  }));
  const open = (i: number, from: HTMLElement) => { openedFrom.current = from; setViewing(i); };
  const step = (delta: number) => setAt((i) => (i + delta + count) % count);

  const arrow = "flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-white hover:bg-black/75 focus:outline-none focus-visible:ring-2 focus-visible:ring-white";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <span className="font-semibold">{allFrames.length}</span> frame{allFrames.length === 1 ? "" : "s"}
          <span className="text-[var(--muted)]"> · two a second, from the drone&apos;s camera</span>
          {markedCount > 0 && <> · <span className="font-semibold">{markedCount}</span> taken during an anomaly, outlined</>}
        </p>
        {markedCount > 0 && (
          <button type="button" onClick={() => { setOnlyMarked((v) => !v); setAt(0); }}
                  aria-pressed={onlyMarked}
                  className={`inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-medium ${
                    onlyMarked ? "bg-[var(--primary)] text-[var(--on-primary)]" : "hover:bg-[var(--surface-2)]"}`}>
            Only anomaly frames
          </button>
        )}
        {enhancedCount > 0 && (
          <div role="group" aria-label="Which frames to show" className="inline-flex rounded-lg border border-[var(--border)]">
            {VIEWS.map((v) => (
              <button key={v.key} type="button" onClick={() => setView(v.key)}
                      aria-pressed={view === v.key}
                      className={`inline-flex min-h-11 items-center px-3 text-sm font-medium first:rounded-l-lg last:rounded-r-lg ${
                        view === v.key ? "bg-[var(--primary)] text-[var(--on-primary)]" : "hover:bg-[var(--surface-2)]"}`}>
                {v.label}
              </button>
            ))}
          </div>
        )}
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
                aria-label={`View ${describe(f)} full screen${marks[f.seq]?.length ? `, taken during: ${marks[f.seq][0].title}` : ""}`}
                className="group relative block aspect-[4/3] w-full cursor-zoom-in overflow-hidden rounded-lg bg-black ring-1 ring-[var(--border)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
                {...hover(f)}
              >
                <Image src={src(f)} alt="" fill unoptimized sizes="16vw"
                       className="object-contain transition-transform duration-300 group-hover:scale-105" />
                {marks[f.seq]?.length ? <MarkBadge marks={marks[f.seq]} /> : null}
                <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-lg" style={markStyle(f)} />
                <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white">
                  {f.seq}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <>
          {/* Side by side: the original beside its enhanced copy. */}
          {view === "both" && (
            <div className="grid max-w-5xl gap-3 sm:grid-cols-2">
              {(["original", "enhanced"] as const).map((which) => {
                const url = which === "original" ? current.url : enhanced[current.seq];
                return (
                  <figure key={which} className="m-0">
                    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-xl bg-black">
                      {url ? (
                        <Image src={url} alt={`Camera frame ${current.seq}, ${which}`} fill unoptimized
                               sizes="(max-width: 640px) 100vw, 50vw" className="object-contain" />
                      ) : (
                        <p className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-white">
                          No enhanced copy of this frame.
                        </p>
                      )}
                    </div>
                    <figcaption className="mt-1 text-xs font-semibold">
                      {which === "original" ? "Original — what the camera saw" : "Enhanced — contrast, nothing added"}
                    </figcaption>
                  </figure>
                );
              })}
            </div>
          )}
          {/* The carousel: one frame, large, never cropped. */}
          <figure className={view === "both" ? "hidden" : undefined}>
            <div className="relative aspect-[4/3] w-full max-w-3xl overflow-hidden rounded-xl bg-black">
              <button
                type="button"
                onClick={(e) => open(at, e.currentTarget)}
                aria-label={`View ${describe(current)} full screen`}
                {...hover(current)}
                className="absolute inset-0 cursor-zoom-in focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
              >
                <Image src={src(current)} alt={`Camera frame ${current.seq}${isEnhanced(current) ? ", enhanced" : ""}`}
                       fill unoptimized sizes="(max-width: 768px) 100vw, 768px" className="object-contain" />
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
              {isEnhanced(current) && (
                <span className={`absolute left-3 rounded bg-black/70 px-2 py-1 text-xs font-semibold text-white ${
                  currentMarks.length ? "top-12" : "top-3"}`}>
                  Enhanced
                </span>
              )}
              {currentMarks.length > 0 && (
                <>
                  <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-xl"
                        style={{ boxShadow: `inset 0 0 0 4px ${groupColor(currentMarks[0].group)}` }} />
                  <span className="pointer-events-none absolute left-3 top-3"><MarkBadge marks={currentMarks} large /></span>
                </>
              )}
            </div>
            <figcaption className="mt-2 font-mono text-xs text-[var(--muted)]">{describe(current)}</figcaption>
          </figure>

          {/* Every frame, small — jump anywhere without paging. */}
          {view === "both" && (
            <p className="font-mono text-xs text-[var(--muted)]">{describe(current)}</p>
          )}
          {currentMarks.length > 0 && (
            <ul className="max-w-3xl space-y-1.5" aria-label="Anomalies this frame was taken during">
              {currentMarks.map((m) => (
                <li key={m.id} className="rounded-md border border-[var(--border)] border-l-4 bg-[var(--surface)] p-2 text-sm"
                    style={{ borderLeftColor: groupColor(m.group) }}>
                  <span className="font-semibold">{SEVERITY[m.severity].label} · {m.title}.</span> {m.body}
                </li>
              ))}
            </ul>
          )}
          {count > 1 && (
            <ol className="flex gap-2 overflow-x-auto [contain:paint] pb-2" aria-label="All frames">
              {frames.map((f, i) => (
                <li key={f.seq} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => setAt(i)}
                    aria-label={`${describe(f)}${marks[f.seq]?.length ? `, taken during: ${marks[f.seq][0].title}` : ""}`}
                    aria-current={i === at ? "true" : undefined}
                    {...hover(f)}
                    className={`relative block h-14 w-[4.7rem] overflow-hidden rounded-md bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] ${
                      i === at ? "ring-2 ring-[var(--primary)]" : "opacity-70 ring-1 ring-[var(--border)] hover:opacity-100"
                    }`}
                  >
                    <Image src={src(f)} alt="" fill unoptimized sizes="76px" className="object-contain" />
                    {marks[f.seq]?.length ? (
                      <span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-md" style={markStyle(f)} />
                    ) : null}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </>
      )}

      <PhotoViewer photos={photos} index={viewing} onIndex={setViewing} restoreFocusTo={openedFrom} />
      {hint.bubble}
    </div>
  );
}
