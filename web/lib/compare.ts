import type { FlightRow, TelemetryRow } from "@/lib/queries";

/**
 * Pure logic for /app/compare: the URL-encoded selection, and the merged rows.
 *
 * Kept free of I/O and React so the rules below can be read and reasoned about
 * in one place.
 */

export const MAX_COMPARE = 4;
export type Slot = 1 | 2 | 3 | 4;
export type Selection = { id: string; slot: Slot }[];

export const METRICS = {
  corrected_temp: { label: "Corrected temperature", kind: "temp" },
  raw_temp: { label: "Raw temperature", kind: "temp" },
  height_m: { label: "Height above ground", unit: "m", kind: "plain", digits: 3 },
  battery_v: { label: "Battery", unit: "V", kind: "plain", digits: 2 },
  station_pressure_hpa: { label: "Station pressure", unit: "hPa", kind: "plain", digits: 2 },
} as const;
export type Metric = keyof typeof METRICS;

export function isMetric(value: unknown): value is Metric {
  return typeof value === "string" && value in METRICS;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Read `?f=<uuid>:<slot>` params.
 *
 * The colour slot travels with the flight in the URL. Colour follows the
 * entity, never its rank: deselecting the first flight must not repaint the
 * second one, which is what deriving slots from list position would do.
 * Invalid, duplicate and over-limit entries are dropped, never trusted.
 */
export function parseSelection(raw: string | string[] | undefined): Selection {
  const values = raw === undefined ? [] : Array.isArray(raw) ? raw : [raw];
  const selection: Selection = [];
  for (const value of values) {
    const [id, slotText] = value.split(":");
    const slot = Number(slotText);
    if (!UUID.test(id ?? "")) continue;
    if (![1, 2, 3, 4].includes(slot)) continue;
    if (selection.some((s) => s.id === id || s.slot === slot)) continue;
    selection.push({ id, slot: slot as Slot });
    if (selection.length === MAX_COMPARE) break;
  }
  return selection;
}

/** The selection after toggling one flight: removed if present, else added in the lowest free slot. */
export function toggle(selection: Selection, id: string): Selection | null {
  if (selection.some((s) => s.id === id)) return selection.filter((s) => s.id !== id);
  const free = ([1, 2, 3, 4] as const).find((slot) => !selection.some((s) => s.slot === slot));
  if (free === undefined) return null; // full: the page shows why it cannot add
  return [...selection, { id, slot: free }];
}

export function compareHref(base: string, selection: Selection, metric: Metric): string {
  const params = new URLSearchParams();
  for (const s of selection) params.append("f", `${s.id}:${s.slot}`);
  params.set("metric", metric);
  return `${base}?${params.toString()}`;
}

/** °F ↔ °C. Temperatures are stored in the unit the operator chose at launch. */
export function convertTemp(value: number, from: string, to: string): number {
  if (from === to) return value;
  return to === "C" ? ((value - 32) * 5) / 9 : (value * 9) / 5 + 32;
}

/** Samples are bucketed to this many seconds so flights sampled at slightly different instants line up. */
export const BUCKET_S = 0.5;

/**
 * One row per time bucket, one column per flight: `{ t, f1, f2, ... }`.
 *
 * x is seconds since each flight's own first sample, so flights started at
 * different times are compared by how far into the flight they were.
 */
export function mergeForChart(
  flights: { flight: FlightRow; slot: Slot; telemetry: TelemetryRow[] }[],
  metric: Metric,
  displayUnit: string,
): Record<string, number | null>[] {
  const buckets = new Map<number, Record<string, number | null>>();

  for (const { slot, telemetry } of flights) {
    const first = telemetry[0] ? Date.parse(telemetry[0].recorded_at) : 0;
    for (const row of telemetry) {
      const value = metricValue(row, metric, displayUnit);
      if (value === null) continue;
      const t = Math.round((Date.parse(row.recorded_at) - first) / 1000 / BUCKET_S) * BUCKET_S;
      const key = Math.round(t * 10) / 10;
      const bucket = buckets.get(key) ?? { t: key };
      bucket[`f${slot}`] = value; // last sample in the bucket wins
      buckets.set(key, bucket);
    }
  }

  return [...buckets.values()].sort((a, b) => (a.t as number) - (b.t as number));
}

function metricValue(row: TelemetryRow, metric: Metric, displayUnit: string): number | null {
  switch (metric) {
    case "corrected_temp":
    case "raw_temp": {
      const v = row[metric];
      return v == null ? null : convertTemp(v, row.temp_unit, displayUnit);
    }
    case "height_m":
      // Already ground-relative: the agent stores `z_m` as metres above the
      // floor captured at takeoff, so flights in rooms with different
      // Lighthouse origins are directly comparable.
      return row.z_m;
    case "battery_v":
      return row.battery_v;
    case "station_pressure_hpa":
      return row.station_pressure_hpa;
    default: {
      const unhandled: never = metric;
      return unhandled;
    }
  }
}
