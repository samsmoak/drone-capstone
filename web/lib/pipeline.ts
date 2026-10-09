/**
 * The data pipeline's result, as the web reads it from public.pipeline_results
 * and public.pipeline_findings (migration 20261009000016) — the shapes the
 * agent's result.json has (backend/agent/cropwatcher/pipeline/contracts.py).
 *
 * The JSON columns come back as `Json`; every reader here checks the shape it
 * needs and drops what does not fit, so a result from an older pipeline
 * version shows what it has instead of breaking the page.
 */

import type { Json } from "@/types/database";

export type Severity = "info" | "warning" | "critical";

/** One analysed signal: what was measured (after any correction) and what
 *  was expected, reading by reading. */
export type Track = {
  signal: "temperature" | "pressure";
  column: string;
  unit: string;
  model: string;
  noise: number | null;
  indexes: number[];
  observed: number[];
  expected: number[];
};

/** [reading index, column (null = whole row), kind, reason] */
export type Flag = { index: number; column: string | null; kind: string; reason: string };

export type FrameQuality = {
  sharpness: number;
  brightness: number;
  usable: boolean;
  reason: string | null;
};

export type FrameRecord = {
  seq: number;
  t_s: number;
  point_id: string | null;
  enhanced: string | null;
  method: string;
  quality: FrameQuality | null;
  label: { value: string; reason: string | null; model: string };
};

export type PointVerdict = {
  point_id: string;
  verdict: "normal" | "anomaly" | "insufficient_data";
  reasons: string[];
};

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isNumbers = (v: unknown): v is number[] =>
  Array.isArray(v) && v.every((x) => typeof x === "number");

export function readTracks(value: Json): Track[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((t) => {
    if (!isObject(t)) return [];
    const { signal, column, unit, model, noise, indexes, observed, expected } = t;
    if ((signal !== "temperature" && signal !== "pressure") || typeof column !== "string"
        || typeof unit !== "string" || typeof model !== "string"
        || !isNumbers(indexes) || !isNumbers(observed) || !isNumbers(expected)) return [];
    return [{ signal, column, unit, model, noise: typeof noise === "number" ? noise : null,
              indexes, observed, expected }];
  });
}

export function readFlags(value: Json): Flag[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((f) =>
    Array.isArray(f) && typeof f[0] === "number" && typeof f[2] === "string"
      ? [{ index: f[0], column: typeof f[1] === "string" ? f[1] : null, kind: f[2],
           reason: typeof f[3] === "string" ? f[3] : "" }]
      : []);
}

export function readFrames(value: Json): FrameRecord[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((f) => {
    if (!isObject(f) || typeof f.seq !== "number") return [];
    const q = isObject(f.quality) ? f.quality : null;
    const label = isObject(f.label) ? f.label : {};
    return [{
      seq: f.seq,
      t_s: typeof f.t_s === "number" ? f.t_s : 0,
      point_id: typeof f.point_id === "string" ? f.point_id : null,
      enhanced: typeof f.enhanced === "string" ? f.enhanced : null,
      method: typeof f.method === "string" ? f.method : "identity",
      quality: q && typeof q.sharpness === "number" && typeof q.brightness === "number"
        ? { sharpness: q.sharpness, brightness: q.brightness, usable: q.usable !== false,
            reason: typeof q.reason === "string" ? q.reason : null }
        : null,
      label: {
        value: typeof label.value === "string" ? label.value : "unknown",
        reason: typeof label.reason === "string" ? label.reason : null,
        model: typeof label.model === "string" ? label.model : "",
      },
    }];
  });
}

export function readPoints(value: Json): PointVerdict[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((p) => {
    if (!isObject(p) || typeof p.point_id !== "string") return [];
    const verdict = p.verdict === "normal" || p.verdict === "anomaly" ? p.verdict
      : "insufficient_data";
    const reasons = Array.isArray(p.reasons) ? p.reasons.filter((r): r is string =>
      typeof r === "string") : [];
    return [{ point_id: p.point_id, verdict, reasons }];
  });
}

export const SEVERITY: Record<Severity, { status: "critical" | "serious" | "warning";
                                          label: string; rank: number }> = {
  critical: { status: "critical", label: "Critical", rank: 2 },
  warning: { status: "serious", label: "Warning", rank: 1 },
  info: { status: "warning", label: "Slight", rank: 0 },
};

export function severityOf(value: string): Severity {
  return value === "critical" || value === "warning" ? value : "info";
}

/** "°C", "°F" or the unit as written. */
export function unitSymbol(unit: string): string {
  return unit === "C" ? "°C" : unit === "F" ? "°F" : unit;
}

/** m:ss from a number of seconds. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * A stretch of a flight the pipeline found anomalous, as the readings table
 * and the camera mark it: the readings it covers (telemetry `index`,
 * inclusive — the agent's Reading.index), its time, and what it means.
 */
export type Highlight = {
  id: string;
  signal: string;
  severity: Severity;
  start: number;
  end: number;
  tStart: number;
  tEnd: number;
  title: string;
  sentence: string;
};

type FindingLike = {
  id: string; signal: string; severity: string; start_index: number; end_index: number;
  t_start_s: number; t_end_s: number; title: string; sentence: string; evidence_frames: number[];
};

export function highlightsOf(findings: readonly FindingLike[]): Highlight[] {
  return findings.map((f) => ({
    id: f.id, signal: f.signal, severity: severityOf(f.severity),
    start: f.start_index, end: f.end_index, tStart: f.t_start_s, tEnd: f.t_end_s,
    title: f.title, sentence: f.sentence,
  })).sort((a, b) => a.start - b.start);
}

/** The worst highlight covering a reading, or undefined. */
export function highlightAt(highlights: readonly Highlight[], index: number): Highlight | undefined {
  let worst: Highlight | undefined;
  for (const h of highlights) {
    if (index < h.start || index > h.end) continue;
    if (!worst || SEVERITY[h.severity].rank > SEVERITY[worst.severity].rank) worst = h;
  }
  return worst;
}

/** Frame seq → the findings that frame was taken during. */
export function frameMarks(findings: readonly FindingLike[]): Record<number, Highlight[]> {
  const out: Record<number, Highlight[]> = {};
  const all = highlightsOf(findings);
  findings.forEach((f) => {
    const h = all.find((x) => x.id === f.id);
    if (!h) return;
    for (const seq of f.evidence_frames) (out[seq] ??= []).push(h);
  });
  for (const list of Object.values(out)) {
    list.sort((a, b) => SEVERITY[b.severity].rank - SEVERITY[a.severity].rank);
  }
  return out;
}

/** The CSS colour of a severity — a status token, never a raw colour. */
export function severityColor(severity: Severity): string {
  return `var(--status-${SEVERITY[severity].status})`;
}

/** One reading of an anomalous stretch: the stored value, and what the
 *  pipeline measured (after any correction) against what it expected. */
export type ExcerptRow = {
  index: number;
  t: number;
  raw: number | null;
  measured: number | null;
  expected: number | null;
};

/**
 * The readings of a stretch, at most `max` of them: the first, the last, the
 * one furthest from what was expected, and evenly between — so a long
 * stretch reads in a glance without hiding where it peaked.
 */
export function excerptOf(
  rows: readonly { index: number; recorded_at: string; [key: string]: unknown }[],
  track: Track | null,
  tStart: number,
  rawColumn: string,
  max = 10,
): { rows: ExcerptRow[]; total: number } {
  if (rows.length === 0) return { rows: [], total: 0 };
  const at = new Map<number, number>();
  track?.indexes.forEach((index, i) => at.set(index, i));
  const first = Date.parse(rows[0].recorded_at);
  const all: ExcerptRow[] = rows.map((r) => {
    const i = at.get(r.index);
    const raw = r[rawColumn];
    return {
      index: r.index,
      t: tStart + (Date.parse(r.recorded_at) - first) / 1000,
      raw: typeof raw === "number" ? raw : null,
      measured: i !== undefined && track ? track.observed[i] : null,
      expected: i !== undefined && track ? track.expected[i] : null,
    };
  });
  if (all.length <= max) return { rows: all, total: all.length };
  const gap = (r: ExcerptRow) =>
    r.measured !== null && r.expected !== null ? Math.abs(r.measured - r.expected) : -1;
  const peak = all.reduce((best, r, i) => (gap(r) > gap(all[best]) ? i : best), 0);
  const keep = new Set([0, all.length - 1, peak]);
  for (let k = 1; keep.size < max && k < max; k++) {
    keep.add(Math.round((k * (all.length - 1)) / (max - 1)));
  }
  return { rows: [...keep].sort((a, b) => a - b).map((i) => all[i]), total: all.length };
}

/** The stored column an anomaly's signal is read from, and what to call it. */
export function rawColumnOf(signal: string, track: Track | null): { column: string; label: string } {
  if (signal === "pressure") return { column: "station_pressure_hpa", label: "Stored pressure" };
  return { column: track?.column ?? "raw_temp", label: "Stored temp" };
}

/** Each finding's excerpt, from its flight's result and its stretch's readings. */
export function excerptsFor(
  findings: readonly { id: string; flight_id: string; signal: string; t_start_s: number }[],
  tracksOf: (flightId: string) => Track[],
  readings: Record<string, { index: number; recorded_at: string; [key: string]: unknown }[]>,
): Record<string, { rows: ExcerptRow[]; total: number; rawLabel: string }> {
  const out: Record<string, { rows: ExcerptRow[]; total: number; rawLabel: string }> = {};
  for (const f of findings) {
    const track = tracksOf(f.flight_id).find((t) => t.signal === f.signal) ?? null;
    const raw = rawColumnOf(f.signal, track);
    out[f.id] = { ...excerptOf(readings[f.id] ?? [], track, f.t_start_s, raw.column), rawLabel: raw.label };
  }
  return out;
}
