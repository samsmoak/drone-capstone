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
