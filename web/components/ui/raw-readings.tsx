"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { TelemetryRow } from "@/lib/queries";
import { formatLocal, useIsClient } from "@/components/ui/local-time";
import { useHint, type HintText } from "@/components/ui/hint";
import { SEVERITY, clock, highlightAt, severityColor, type Highlight } from "@/lib/pipeline";

/**
 * Every stored column of every sample, paged.
 *
 * Paged rather than capped: a flight's raw rows are the evidence when a chart
 * looks wrong, and quietly showing only the first N would hide exactly the end
 * of the flight where things usually go wrong.
 *
 * ANOMALIES ARE MARKED (the owner, 2026-10-09): with the pipeline's findings
 * given as `highlights`, every reading inside an anomalous stretch is tinted
 * in its severity's colour, with the severity's shape in the first cell (never
 * colour alone). Hovering a marked row, focusing its marker or tapping it says
 * what the anomaly means. A list above the table jumps to each stretch, since
 * one may be pages away.
 */

const PAGE_SIZE = 100;

/** One column of the table: a field of the row, its label, its decimals. */
export type ReadingColumn = { key: string; label: string; digits?: number };

/** Any stored row — a flight's telemetry, or a session's own samples. */
type ReadingRow = { [key: string]: unknown };

const COLUMNS: (ReadingColumn & { key: keyof TelemetryRow })[] = [
  { key: "index", label: "#" },
  { key: "recorded_at", label: "Recorded" },
  { key: "mode", label: "Mode" },
  { key: "event", label: "Event" },
  { key: "x_m", label: "x (m)", digits: 3 },
  { key: "y_m", label: "y (m)", digits: 3 },
  { key: "z_m", label: "z (m)", digits: 3 },
  { key: "battery_v", label: "Battery (V)", digits: 2 },
  { key: "thrust", label: "Thrust", digits: 0 },
  { key: "raw_temp", label: "Raw temp", digits: 2 },
  { key: "corrected_temp", label: "Corrected temp", digits: 2 },
  { key: "ambient_est", label: "Ambient est.", digits: 2 },
  { key: "thermal_offset", label: "Thermal offset", digits: 2 },
  { key: "thermal_state", label: "Thermal state" },
  { key: "station_pressure_hpa", label: "Pressure (hPa)", digits: 2 },
  { key: "sea_level_pressure_hpa", label: "Sea-level (hPa)", digits: 2 },
  { key: "pressure_altitude_m", label: "Pressure alt. (m)", digits: 2 },
  { key: "air_density_kg_m3", label: "Air density (kg/m³)", digits: 4 },
  { key: "roc_per_s", label: "Rate of change (/s)", digits: 3 },
];

function cell(row: ReadingRow, key: string, client: boolean, digits?: number): string {
  const value = row[key];
  if (value === null || value === undefined) return "—";
  // Viewer's timezone once in the browser; an explicit UTC ISO string before.
  if (key === "recorded_at") return client ? formatLocal(String(value), "time") : String(value);
  if (typeof value === "number" && digits !== undefined) return value.toFixed(digits);
  return String(value);
}

function hintOf(h: Highlight): HintText {
  const sev = SEVERITY[h.severity];
  return {
    title: h.title,
    body: `${h.sentence} Readings ${h.start}–${h.end}, ${clock(h.tStart)}–${clock(h.tEnd)} into the flight.`,
    label: sev.label,
    color: severityColor(h.severity),
  };
}

const ICON = { critical: "■", serious: "▲", warning: "▲" } as const;

export function RawReadings({ rows, unit, columns = COLUMNS, what = "flight", highlights = [] }: {
  rows: ReadingRow[];
  unit: string;
  /** The flight's columns unless given (a session's samples have their own). */
  columns?: ReadingColumn[];
  /** Named in the empty state: "flight" or "session". */
  what?: string;
  /** The pipeline's anomalous stretches, by reading index (flights only). */
  highlights?: Highlight[];
}) {
  const client = useIsClient();
  const [page, setPage] = useState(0);
  const hint = useHint();
  const region = useRef<HTMLDivElement>(null);
  // A jump: which reading to bring into view, once its page has rendered.
  const jumpTo = useRef<number | null>(null);
  const [jumps, setJumps] = useState(0);
  const marked = useMemo(
    () => (highlights.length ? rows.filter((r) => typeof r.index === "number"
      && highlightAt(highlights, r.index as number)).length : 0),
    [rows, highlights]);

  // After a jump, bring the stretch's first reading into view in the box.
  useEffect(() => {
    if (jumpTo.current === null) return;
    const row = region.current?.querySelector<HTMLElement>(`[data-reading="${jumpTo.current}"]`);
    if (row && region.current) {
      region.current.scrollTop = row.offsetTop - 40;
      region.current.scrollIntoView({ block: "nearest" });
    }
    jumpTo.current = null;
  }, [jumps]);

  const jump = (h: Highlight) => {
    const at = rows.findIndex((r) => typeof r.index === "number" && (r.index as number) >= h.start);
    if (at < 0) return;
    jumpTo.current = rows[at].index as number;
    setPage(Math.floor(at / PAGE_SIZE));
    setJumps((n) => n + 1);
  };
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const first = page * PAGE_SIZE + 1;
  const last = Math.min(rows.length, (page + 1) * PAGE_SIZE);

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
        No readings were stored for this {what}.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {highlights.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm">
            <span className="font-semibold">{marked.toLocaleString()}</span> reading{marked === 1 ? "" : "s"} inside{" "}
            {highlights.length} anomal{highlights.length === 1 ? "y" : "ies"}, tinted below. Hover a tinted
            row, or focus or tap its marker, for what it means.
          </p>
          <ul className="flex flex-wrap gap-2" aria-label="Go to an anomaly in the table">
            {highlights.map((h) => {
              const sev = SEVERITY[h.severity];
              return (
                <li key={h.id}>
                  <button type="button" onClick={() => jump(h)}
                          className="inline-flex min-h-11 items-center gap-2 rounded-md border border-[var(--border)] border-l-4 bg-[var(--surface)] px-3 text-left text-xs hover:bg-[var(--surface-2)]"
                          style={{ borderLeftColor: severityColor(h.severity) }}>
                    <span aria-hidden="true" style={{ color: severityColor(h.severity) }}>{ICON[sev.status]}</span>
                    <span>
                      <span className="font-semibold">{sev.label}</span> · {h.title} · readings {h.start}–{h.end}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {/* Scrolls inside its own box, header pinned, so a page of readings does
          not push the rest of the flight off the bottom of the screen. The
          region is focusable so it can be scrolled from the keyboard. */}
      <div
        ref={region}
        tabIndex={0}
        role="region"
        aria-label="Raw readings table"
        className="relative max-h-[32rem] overflow-auto rounded-lg border border-[var(--border)]"
      >
        <table className="w-full border-collapse text-left text-xs">
          <caption className="sr-only">
            Raw readings {first} to {last} of {rows.length}. Temperatures in °{unit}.
            {highlights.length > 0 && ` ${marked} readings are inside an anomaly; their first cell says which.`}
          </caption>
          <thead className="sticky top-0 bg-[var(--surface-2)]">
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => {
              const h = typeof row.index === "number" ? highlightAt(highlights, row.index) : undefined;
              const color = h ? severityColor(h.severity) : undefined;
              const text = h ? hintOf(h) : undefined;
              return (
                <tr
                  key={String(row.id ?? row.seq ?? i)}
                  data-reading={typeof row.index === "number" ? row.index : undefined}
                  className="border-t border-[var(--border)]"
                  style={color ? { backgroundColor: `color-mix(in srgb, ${color} 16%, transparent)` } : undefined}
                  onMouseMove={text ? (e) => hint.show(text, e.currentTarget, e.clientX) : undefined}
                  onMouseLeave={text ? hint.hide : undefined}
                >
                  {columns.map((c, ci) => (
                    <td key={c.key} className="tabular whitespace-nowrap px-3 py-1.5"
                        style={ci === 0 && color ? { boxShadow: `inset 4px 0 0 ${color}` } : undefined}>
                      {ci === 0 && h && text ? (
                        <span className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            aria-label={`${SEVERITY[h.severity].label} anomaly: ${h.title}`}
                            aria-describedby={hint.isOpen ? hint.id : undefined}
                            onFocus={(e) => hint.show(text, e.currentTarget)}
                            onBlur={hint.hideNow}
                            onClick={(e) => hint.toggle(text, e.currentTarget)}
                            className="inline-flex h-6 w-6 items-center justify-center rounded text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
                            style={{ color }}
                          >
                            <span aria-hidden="true">{ICON[SEVERITY[h.severity].status]}</span>
                          </button>
                          {cell(row, c.key, client, c.digits)}
                        </span>
                      ) : cell(row, c.key, client, c.digits)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <nav aria-label="Readings pages" className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-[var(--muted)]" aria-live="polite">
          Rows <span className="tabular text-[var(--foreground)]">{first}–{last}</span> of{" "}
          <span className="tabular text-[var(--foreground)]">{rows.length}</span>
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => p - 1)}
            disabled={page === 0}
            className="min-h-11 rounded-md border border-[var(--border)] px-4 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= pages - 1}
            className="min-h-11 rounded-md border border-[var(--border)] px-4 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </nav>
      {hint.bubble}
    </div>
  );
}
