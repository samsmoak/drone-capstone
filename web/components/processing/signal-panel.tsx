"use client";

import Image from "next/image";
import { useState } from "react";
import { TimeSeries, type Band, type Series } from "@/components/ui/time-series";
import { unitSymbol, type Flag, type Track } from "@/lib/pipeline";

/**
 * One signal of one flight, raw vs clean (the owner, 2026-10-09: "the dirty
 * data versus the clean data").
 *
 *   Clean   what the pipeline analysed — the cleaner's flagged values left out,
 *           pressure corrected for height — against what was EXPECTED (the
 *           drone's cooling curve; the pressure's drift). The stretches that
 *           departed are shaded and named under the chart.
 *   Raw     every value as recorded, the flagged ones marked as points.
 *
 * A CLICK ON THE CHART SHOWS THE CAMERA FRAME NEAREST THAT MOMENT, original
 * beside enhanced, under the chart, with previous / next to step through
 * (2026-10-11: a spike, then what the drone was looking at). The readings are
 * still the evidence; the frame is what the camera saw then, which may be
 * nothing. A frame more than FAR_S from the click says how far.
 *
 * One y-axis, one unit, as every chart here (components/ui/time-series.tsx).
 */

export type RawReading = { index: number; t: number; value: number | null };

/** A frame of this flight, on the chart's clock, with its links. */
export type PanelFrame = {
  seq: number;
  t_s: number;
  original?: string;
  enhanced?: string;
  /** What the pipeline said about it: unreadable, or the scene's note. */
  note: string | null;
};

/** Beyond this many seconds from the click, the frame says how far it is. */
const FAR_S = 1;

function nearest(frames: PanelFrame[], x: number): number {
  let best = 0;
  for (let i = 1; i < frames.length; i++) {
    if (Math.abs(frames[i].t_s - x) < Math.abs(frames[best].t_s - x)) best = i;
  }
  return best;
}

function FrameAt({ frames, at, clicked, onStep, onClose }: {
  frames: PanelFrame[];
  at: number;
  clicked: number;
  onStep: (delta: number) => void;
  onClose: () => void;
}) {
  const f = frames[at];
  const off = Math.abs(f.t_s - clicked);
  const button = "inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-[var(--border)] px-3 text-sm font-medium hover:bg-[var(--surface-2)] disabled:opacity-40";
  return (
    <section aria-label="The camera at that moment" aria-live="polite"
             className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">
          <span className="font-semibold">Frame {f.seq}</span> · {f.t_s.toFixed(1)} s
          {off > FAR_S && <span className="text-[var(--muted)]"> · the nearest frame, {off.toFixed(1)} s from where you clicked</span>}
        </p>
        <div className="flex gap-2">
          <button type="button" className={button} onClick={() => onStep(-1)} disabled={at === 0}
                  aria-label="Previous frame">←</button>
          <button type="button" className={button} onClick={() => onStep(1)} disabled={at === frames.length - 1}
                  aria-label="Next frame">→</button>
          <button type="button" className={button} onClick={onClose}>Close</button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {(["original", "enhanced"] as const).map((which) => (
          <figure key={which} className="m-0">
            <div className="relative aspect-[4/3] overflow-hidden rounded-md bg-black">
              {f[which] ? (
                <Image src={f[which] as string} alt={`Camera frame ${f.seq}, ${which}`} fill unoptimized
                       sizes="(max-width: 1280px) 50vw, 25vw" className="object-contain" />
              ) : (
                <span className="absolute inset-0 flex items-center justify-center p-2 text-center text-xs text-white">
                  {which === "original" ? "Not uploaded yet" : "No enhanced copy"}
                </span>
              )}
            </div>
            <figcaption className="mt-1 text-xs font-semibold">
              {which === "original" ? "Original — what the camera saw" : "Enhanced — contrast, nothing added"}
            </figcaption>
          </figure>
        ))}
      </div>
      {f.note && <p className="text-xs text-[var(--muted)]">{f.note}</p>}
    </section>
  );
}

const VIEWS = [
  { key: "clean", label: "Clean" },
  { key: "raw", label: "Raw" },
] as const;

export function SignalPanel({
  title,
  track,
  raw,
  flags,
  bands,
  over = "flight",
  frames = [],
}: {
  /** The flight's camera frames in time order; empty, and clicks do nothing. */
  frames?: PanelFrame[];
  /** What the clock counts from: "flight", or "session" for a session's own. */
  over?: string;
  title: string;
  track: Track | null;
  /** The track's column as recorded, every reading, on the flight's clock. */
  raw: RawReading[];
  /** The cleaner's flags on this column (or the whole row). */
  flags: Flag[];
  bands: Band[];
}) {
  const [view, setView] = useState<"clean" | "raw">(track ? "clean" : "raw");
  // The frame shown under the chart, and where the click was.
  const [picked, setPicked] = useState<{ at: number; clicked: number } | null>(null);
  const onPick = frames.length > 0
    ? (x: number) => setPicked({ at: nearest(frames, x), clicked: x })
    : undefined;
  const marker = picked ? frames[picked.at].t_s : null;
  const unit = track ? unitSymbol(track.unit) : "";
  const flagged = new Set(flags.map((f) => f.index));
  const time = new Map(raw.map((r) => [r.index, r.t]));

  const rawRows = raw.map((r) => ({
    t: r.t,
    recorded: r.value,
    flagged: flagged.has(r.index) ? r.value : null,
  }));
  const cleanRows = track
    ? track.indexes.flatMap((index, i) => {
        const t = time.get(index);
        return t === undefined ? [] : [{ t, observed: track.observed[i], expected: track.expected[i] }];
      })
    : [];
  const pressure = track?.signal === "pressure";
  const corrected = pressure && !track?.model.includes("height not measured");

  const cleanSeries: Series[] = [
    { key: "observed", label: corrected ? "Corrected for height" : "Measured", slot: 1, unit },
    { key: "expected", label: "Expected", slot: 2, unit },
  ];
  const rawSeries: Series[] = [
    { key: "recorded", label: "As recorded", slot: 1, unit },
    { key: "flagged", label: "Flagged by the cleaner", slot: 2, unit, points: true },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h4 className="text-base font-semibold">{title}{unit ? ` (${unit})` : ""}</h4>
        <div role="group" aria-label={`${title}: which data`}
             className="inline-flex rounded-lg border border-[var(--border)]">
          {VIEWS.map((v) => (
            <button key={v.key} type="button" onClick={() => setView(v.key)}
                    aria-pressed={view === v.key}
                    disabled={v.key === "clean" && !track}
                    className={`inline-flex min-h-11 items-center px-4 text-sm font-medium first:rounded-l-lg last:rounded-r-lg disabled:opacity-40 ${
                      view === v.key ? "bg-[var(--primary)] text-[var(--on-primary)]" : "hover:bg-[var(--surface-2)]"}`}>
              {v.label}
            </button>
          ))}
        </div>
      </div>
      <p className="text-sm text-[var(--muted)]">
        {view === "clean"
          ? track
            ? `What the pipeline analysed, against what was expected (${track.model}). ${
                track.noise !== null ? `Reading-to-reading noise ±${track.noise.toFixed(3)} ${unit}.` : ""}`
            : "Not analysed."
          : `Every value as recorded; ${flagged.size.toLocaleString()} flagged by the cleaner and left out of the analysis.`}
        {frames.length > 0 && " Click the chart to see the camera at that moment."}
      </p>
      {view === "clean" ? (
        <TimeSeries rows={cleanRows} series={cleanSeries} xKey="t" xLabel={`Time in ${over} (s)`}
                    xFormat="seconds" yLabel={unit} digits={pressure ? 3 : 2} bands={bands}
                    onPick={onPick} marker={marker} />
      ) : (
        <TimeSeries rows={rawRows} series={rawSeries} xKey="t" xLabel={`Time in ${over} (s)`}
                    xFormat="seconds" yLabel={unit} digits={pressure ? 3 : 2} bands={bands}
                    onPick={onPick} marker={marker} />
      )}
      {picked && (
        <FrameAt frames={frames} at={picked.at} clicked={picked.clicked}
                 onStep={(delta) => setPicked((p) => p && {
                   ...p, at: Math.min(frames.length - 1, Math.max(0, p.at + delta)) })}
                 onClose={() => setPicked(null)} />
      )}
    </div>
  );
}
