"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { formatLocal, useIsClient } from "@/components/ui/local-time";
import { useHint, type HintText } from "@/components/ui/hint";
import { MarkLegend, MarkShape } from "@/components/ui/mark-legend";
import {
  GROUPS,
  SEVERITY,
  clock,
  groupColor,
  groupTint,
  marksAt,
  worstMark,
  type Group,
  type Mark,
} from "@/lib/pipeline";

/**
 * Every stored reading, paged.
 *
 * PAGED, NEVER CAPPED: a flight's raw rows are the evidence when a chart looks
 * wrong, and quietly showing only the first N would hide the end of the flight
 * where things usually go wrong.
 *
 * EVERY ROW OF A PAGE IS VISIBLE (the owner, 2026-10-09): PAGE_SIZE rows of a
 * fixed height, so every page is the same height but the last — no box to
 * scroll inside. Only a screen too narrow for the columns scrolls sideways,
 * with the reading's number held in place.
 *
 * THE COLUMNS THE PIPELINE PROCESSES come first, grouped (Reading · Position ·
 * Power · Temperature · Pressure); "Show all columns" adds the ones it only
 * stores (sea-level pressure, air density, the correction engine's terms…).
 *
 * MARKS (lib/pipeline.ts): an anomaly or a fault tints exactly the cells it is
 * about — the hue its data group, the depth its severity — with its shape in
 * the first cell; hovering a tinted cell, or focusing or tapping the shape,
 * says what it means. A list above jumps to each anomaly; the error table
 * (components/processing/error-table.tsx) jumps here too.
 */

const PAGE_SIZE = 20;

/** One column: a field of the row, its label, its decimals, its header group. */
export type ReadingColumn = {
  key: string;
  label: string;
  digits?: number;
  group: string;
  /** Shown only with "Show all columns". */
  extra?: boolean;
};

/** Any stored row — a flight's telemetry, or a session's own samples. */
type ReadingRow = { [key: string]: unknown };

/** A flight's telemetry (public.telemetry). */
export const FLIGHT_COLUMNS: ReadingColumn[] = [
  { key: "index", label: "#", group: "Reading" },
  { key: "recorded_at", label: "Time", group: "Reading" },
  { key: "point_id", label: "Point", group: "Reading" },
  { key: "mode", label: "Mode", group: "Reading" },
  { key: "event", label: "Event", group: "Reading" },
  { key: "x_m", label: "x (m)", digits: 3, group: "Position" },
  { key: "y_m", label: "y (m)", digits: 3, group: "Position" },
  { key: "z_m", label: "z (m)", digits: 3, group: "Position" },
  { key: "lighthouse_received", label: "Stations", group: "Position", extra: true },
  { key: "battery_v", label: "Battery (V)", digits: 2, group: "Power" },
  { key: "thrust", label: "Thrust", digits: 0, group: "Power", extra: true },
  { key: "raw_temp", label: "Raw", digits: 2, group: "Temperature" },
  { key: "corrected_temp", label: "Corrected", digits: 2, group: "Temperature" },
  { key: "ambient_est", label: "Ambient est.", digits: 2, group: "Temperature", extra: true },
  { key: "thermal_offset", label: "Offset", digits: 2, group: "Temperature", extra: true },
  { key: "thermal_state", label: "State", group: "Temperature", extra: true },
  { key: "roc_per_s", label: "Change (/s)", digits: 3, group: "Temperature", extra: true },
  { key: "station_pressure_hpa", label: "Station (hPa)", digits: 2, group: "Pressure" },
  { key: "sea_level_pressure_hpa", label: "Sea level (hPa)", digits: 2, group: "Pressure", extra: true },
  { key: "pressure_altitude_m", label: "Altitude (m)", digits: 2, group: "Pressure", extra: true },
  { key: "air_density_kg_m3", label: "Air density (kg/m³)", digits: 4, group: "Pressure", extra: true },
];

/** A session's own samples, one a second (public.session_samples). */
export const SESSION_COLUMNS: ReadingColumn[] = [
  { key: "seq", label: "#", group: "Reading" },
  { key: "recorded_at", label: "Time", group: "Reading" },
  { key: "mode", label: "Mode", group: "Reading" },
  { key: "x_m", label: "x (m)", digits: 3, group: "Position" },
  { key: "y_m", label: "y (m)", digits: 3, group: "Position" },
  { key: "z_m", label: "z (m)", digits: 3, group: "Position" },
  { key: "positioned", label: "Positioned", group: "Position", extra: true },
  { key: "lighthouse_received", label: "Stations", group: "Position", extra: true },
  { key: "height_m", label: "Height (m)", digits: 3, group: "Position", extra: true },
  { key: "battery_v", label: "Battery (V)", digits: 2, group: "Power" },
  { key: "thrust", label: "Thrust", digits: 0, group: "Power", extra: true },
  { key: "raw_temp", label: "Sensor (°C)", digits: 2, group: "Temperature" },
  { key: "station_pressure_hpa", label: "Station (hPa)", digits: 2, group: "Pressure" },
  { key: "roll_deg", label: "Roll (°)", digits: 1, group: "Attitude", extra: true },
  { key: "pitch_deg", label: "Pitch (°)", digits: 1, group: "Attitude", extra: true },
  { key: "yaw_deg", label: "Yaw (°)", digits: 1, group: "Attitude", extra: true },
];

/** Asks a readings table to show a reading: the error table's "Show". */
export const JUMP_EVENT = "dronedeck:show-reading";
export type JumpDetail = { table: string; index: number };

function cell(row: ReadingRow, key: string, client: boolean, digits?: number): string {
  const value = row[key];
  if (value === null || value === undefined || value === "") return "—";
  // Viewer's timezone once in the browser; an explicit UTC ISO string before.
  if (key === "recorded_at") return client ? formatLocal(String(value), "time") : String(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number" && digits !== undefined) return value.toFixed(digits);
  return String(value);
}

function hintOf(marks: Mark[]): HintText {
  const worst = worstMark(marks) as Mark;
  const when = worst.tStart !== null && worst.tEnd !== null
    ? ` ${clock(worst.tStart)}–${clock(worst.tEnd)}.` : "";
  const more = marks.length > 1 ? ` And ${marks.length - 1} more here: ${marks
    .filter((m) => m !== worst).map((m) => m.title).join("; ")}.` : "";
  return {
    title: worst.title,
    body: `${worst.body} Readings ${worst.start}–${worst.end}.${when}${more}`,
    label: `${GROUPS[worst.group].label} · ${SEVERITY[worst.severity].label}`,
    color: groupColor(worst.group),
  };
}

export function RawReadings({
  rows, unit, columns = FLIGHT_COLUMNS, what = "flight", marks = [], indexKey = "index",
  id = "readings",
}: {
  rows: ReadingRow[];
  unit: string;
  /** The flight's columns unless given (a session's samples have their own). */
  columns?: ReadingColumn[];
  /** Named in the empty state: "flight" or "session". */
  what?: string;
  /** Anomalies and faults (lib/pipeline anomalyMarks, faultMarks). */
  marks?: Mark[];
  /** The row's reading number: telemetry `index`, or a sample's `seq`. */
  indexKey?: string;
  /** Unique on the page: the error table's "Show" finds this table by it. */
  id?: string;
}) {
  const client = useIsClient();
  const [page, setPage] = useState(0);
  const [all, setAll] = useState(false);
  const hint = useHint();
  const shown = useMemo(() => columns.filter((c) => all || !c.extra), [columns, all]);
  const tableRef = useRef<HTMLTableElement>(null);
  const jumpTo = useRef<number | null>(null);
  const [jumps, setJumps] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const first = page * PAGE_SIZE + 1;
  const last = Math.min(rows.length, (page + 1) * PAGE_SIZE);
  const indexOf = (row: ReadingRow) => (typeof row[indexKey] === "number" ? row[indexKey] as number : null);
  const anomalies = marks.filter((m) => m.kind === "anomaly");
  const groups = [...new Set(marks.map((m) => m.group))] as Group[];
  const marked = useMemo(() => (marks.length
    ? rows.filter((r) => { const i = indexOf(r); return i !== null && marksAt(marks, i).length > 0; }).length
    : 0), [rows, marks]); // eslint-disable-line react-hooks/exhaustive-deps

  // After a jump, the reading's row into view, briefly outlined.
  useEffect(() => {
    if (jumpTo.current === null) return;
    const row = tableRef.current?.querySelector<HTMLElement>(`[data-reading="${jumpTo.current}"]`);
    if (row) {
      row.scrollIntoView({ block: "center", behavior: "smooth" });
      row.focus({ preventScroll: true });
    }
    jumpTo.current = null;
  }, [jumps]);

  const show = (index: number) => {
    const at = rows.findIndex((r) => { const i = indexOf(r); return i !== null && i >= index; });
    if (at < 0) return;
    jumpTo.current = indexOf(rows[at]);
    setPage(Math.floor(at / PAGE_SIZE));
    setJumps((n) => n + 1);
  };

  // The error table asks by event, so the two need no shared state.
  useEffect(() => {
    const listen = (e: Event) => {
      const detail = (e as CustomEvent<JumpDetail>).detail;
      if (detail?.table === id) show(detail.index);
    };
    window.addEventListener(JUMP_EVENT, listen);
    return () => window.removeEventListener(JUMP_EVENT, listen);
  });

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
        No readings were stored for this {what}.
      </p>
    );
  }

  // Header groups: consecutive columns of one group share a heading.
  const headerGroups: { group: string; span: number }[] = [];
  for (const c of shown) {
    const lastGroup = headerGroups[headerGroups.length - 1];
    if (lastGroup && lastGroup.group === c.group) lastGroup.span += 1;
    else headerGroups.push({ group: c.group, span: 1 });
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        {marks.length > 0 ? (
          <p className="max-w-2xl text-sm">
            <span className="font-semibold">{marked.toLocaleString()}</span> of {rows.length.toLocaleString()}{" "}
            readings are marked. The colour is the data, the depth how severe; hover a tinted cell, or
            focus or tap its shape, for what it means.
          </p>
        ) : (
          <p className="text-sm text-[var(--muted)]">
            {rows.length.toLocaleString()} readings{indexKey === "seq" ? ", one a second" : ""}.
          </p>
        )}
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-pressed={all}
          className="inline-flex min-h-11 items-center rounded-md border border-[var(--border)] px-4 text-sm font-medium hover:bg-[var(--surface-2)]"
        >
          {all ? "Show the processed columns" : "Show all columns"}
        </button>
      </div>
      {groups.length > 0 && <MarkLegend groups={groups} />}

      {anomalies.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Go to an anomaly in the table">
          {anomalies.map((m) => (
            <li key={m.id}>
              <button type="button" onClick={() => show(m.start)}
                      className="inline-flex min-h-11 items-center gap-2 rounded-md border border-[var(--border)] border-l-4 px-3 text-left text-xs hover:brightness-95"
                      style={{ borderLeftColor: groupColor(m.group), background: groupTint(m.group, m.severity) }}>
                <MarkShape mark={m} />
                <span>
                  <span className="font-semibold">{SEVERITY[m.severity].label}</span> · {m.title} · readings {m.start}–{m.end}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Sideways only, and only when the screen is narrower than the columns. */}
      <div className="relative overflow-x-auto rounded-lg border border-[var(--border)]">
        <table ref={tableRef} className="w-full border-collapse text-left text-xs">
          <caption className="sr-only">
            Readings {first} to {last} of {rows.length}. Temperatures in °{unit}.
            {marks.length > 0 && ` ${marked} readings are marked; the first cell of a marked row says how.`}
          </caption>
          <thead className="bg-[var(--surface-2)]">
            <tr>
              {headerGroups.map((g, i) => (
                <th key={`${g.group}-${i}`} scope="colgroup" colSpan={g.span}
                    className={`border-b border-[var(--border)] px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide ${
                      i > 0 ? "border-l" : ""} ${i === 0 ? "sticky left-0 z-[1] bg-[var(--surface-2)]" : ""}`}>
                  {g.group}
                </th>
              ))}
            </tr>
            <tr>
              {shown.map((c, ci) => (
                <th key={c.key} scope="col"
                    className={`whitespace-nowrap px-3 py-2 font-medium ${c.digits !== undefined ? "text-right" : ""} ${
                      ci === 0 ? "sticky left-0 z-[1] bg-[var(--surface-2)]" : ""}`}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => {
              const index = indexOf(row);
              const here = index !== null ? marksAt(marks, index) : [];
              const worst = worstMark(here);
              return (
                <tr
                  key={String(row.id ?? row[indexKey] ?? i)}
                  data-reading={index ?? undefined}
                  tabIndex={-1}
                  className="h-9 border-t border-[var(--border)] bg-[var(--surface)] even:bg-[var(--surface-2)] focus:outline-2 focus:outline-[var(--primary)]"
                >
                  {shown.map((c, ci) => {
                    const mine = here.filter((m) => m.columns.includes(c.key));
                    const top = worstMark(mine);
                    const tint = top ? groupTint(top.group, top.severity) : undefined;
                    const sticky = ci === 0;
                    const style: React.CSSProperties = {};
                    if (sticky) {
                      // Opaque, so the columns scrolling under it stay hidden; the row's
                      // stripe under the tint.
                      if (tint) style.backgroundImage = `linear-gradient(${tint}, ${tint})`;
                      if (worst) style.boxShadow = `inset 4px 0 0 ${groupColor(worst.group)}`;
                    } else if (tint) {
                      style.background = tint;
                    }
                    const text = top ? hintOf(mine) : undefined;
                    return (
                      <td
                        key={c.key}
                        className={`tabular whitespace-nowrap px-3 ${c.digits !== undefined ? "text-right" : ""} ${
                          sticky ? "sticky left-0 z-[1] bg-inherit" : ""}`}
                        style={style}
                        onMouseMove={text ? (e) => hint.show(text, e.currentTarget, e.clientX) : undefined}
                        onMouseLeave={text ? hint.hide : undefined}
                      >
                        {sticky && here.length > 0 ? (
                          <span className="inline-flex items-center gap-1.5">
                            <button
                              type="button"
                              aria-label={`Marked: ${here.map((m) => `${SEVERITY[m.severity].label} ${GROUPS[m.group].label.toLowerCase()}, ${m.title}`).join("; ")}`}
                              aria-describedby={hint.isOpen ? hint.id : undefined}
                              onFocus={(e) => hint.show(hintOf(here), e.currentTarget)}
                              onBlur={hint.hideNow}
                              onClick={(e) => hint.toggle(hintOf(here), e.currentTarget)}
                              className="inline-flex h-6 min-w-6 items-center justify-center gap-0.5 rounded px-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
                            >
                              {[...new Map(here.map((m) => [m.group, m])).values()].map((m) => (
                                <MarkShape key={m.group} mark={m} />
                              ))}
                            </button>
                            {cell(row, c.key, client, c.digits)}
                          </span>
                        ) : cell(row, c.key, client, c.digits)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <nav aria-label="Readings pages" className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-[var(--muted)]" aria-live="polite">
          Rows <span className="tabular text-[var(--foreground)]">{first}–{last}</span> of{" "}
          <span className="tabular text-[var(--foreground)]">{rows.length}</span> · page{" "}
          <span className="tabular text-[var(--foreground)]">{page + 1}</span> of {pages}
        </p>
        <div className="flex gap-2">
          <button type="button" onClick={() => setPage(0)} disabled={page === 0}
                  className="min-h-11 rounded-md border border-[var(--border)] px-3 disabled:opacity-50">
            First
          </button>
          <button type="button" onClick={() => setPage((p) => p - 1)} disabled={page === 0}
                  className="min-h-11 rounded-md border border-[var(--border)] px-4 disabled:opacity-50">
            Previous
          </button>
          <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= pages - 1}
                  className="min-h-11 rounded-md border border-[var(--border)] px-4 disabled:opacity-50">
            Next
          </button>
          <button type="button" onClick={() => setPage(pages - 1)} disabled={page >= pages - 1}
                  className="min-h-11 rounded-md border border-[var(--border)] px-3 disabled:opacity-50">
            Last
          </button>
        </div>
      </nav>
      {hint.bubble}
    </div>
  );
}
