"use client";

import { useMemo, useState } from "react";
import { formatLocal, useIsClient } from "@/components/ui/local-time";
import { MarkShape } from "@/components/ui/mark-legend";
import { JUMP_EVENT, type JumpDetail } from "@/components/ui/raw-readings";
import { SEVERITY, clock, groupColor, groupTint, type Mark } from "@/lib/pipeline";

/**
 * Only what went wrong (the owner, 2026-10-09: "a table for just error data,
 * with the timestamp and where it occurred — not every column filled, it
 * depends on the error; the time increasing but not contiguous").
 *
 * ONE ROW PER SPAN: an anomaly the pipeline found, or a run of readings the
 * cleaner flagged the same way (lib/pipeline faultMarks). In time order; where
 * time passed between two spans the table says how much, because the readings
 * in between were fine. The value columns are filled only for the data the
 * span is about — a pressure step leaves temperature blank — with the range
 * the readings took during it. "Show" opens those readings in the full table.
 */

const PAGE_SIZE = 12;

type ReadingRow = { [key: string]: unknown };

function range(rows: ReadingRow[], key: string, digits: number): string | null {
  const values = rows.map((r) => r[key]).filter((v): v is number => typeof v === "number");
  if (values.length === 0) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  return lo === hi ? lo.toFixed(digits) : `${lo.toFixed(digits)} – ${hi.toFixed(digits)}`;
}

function mean(rows: ReadingRow[], key: string): number | null {
  const values = rows.map((r) => r[key]).filter((v): v is number => typeof v === "number");
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

/** A short name for what a span is about — the chip must fit on one line. */
function shortLabel(m: Mark): string {
  if (m.kind === "anomaly") return m.group === "pressure" ? "Pressure" : "Temperature";
  if (m.columns.includes("battery_v")) return "Battery";
  if (m.columns.includes("x_m")) return "Position";
  if (m.columns.includes("station_pressure_hpa")) return "Pressure sensor";
  if (m.columns.includes("raw_temp")) return "Temp sensor";
  return "Readings lost";
}

export function ErrorTable({ marks, rows, indexKey = "index", table, unit, what = "flight" }: {
  marks: Mark[];
  rows: ReadingRow[];
  indexKey?: string;
  /** The readings table's id on this page (RawReadings `id`), for "Show". */
  table: string;
  unit: string;
  what?: string;
}) {
  const client = useIsClient();
  const [page, setPage] = useState(0);
  const byIndex = useMemo(() => {
    const m = new Map<number, ReadingRow>();
    for (const r of rows) if (typeof r[indexKey] === "number") m.set(r[indexKey] as number, r);
    return m;
  }, [rows, indexKey]);
  const ordered = useMemo(() => [...marks].sort((a, b) =>
    (a.tStart ?? a.start) - (b.tStart ?? b.start) || a.start - b.start), [marks]);

  if (ordered.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm">
        Nothing went wrong in this {what}: no anomaly, and no reading the cleaner had to flag.
      </p>
    );
  }

  // The value columns some span is about — never a column of blanks. Position
  // is not one: "Where" already says where.
  const VALUES = [
    { key: "temp", label: `Temp (${unit === "F" ? "°F" : "°C"})`, keys: ["raw_temp", "corrected_temp"], column: "raw_temp" },
    { key: "pressure", label: "Pressure (hPa)", keys: ["station_pressure_hpa"], column: "station_pressure_hpa" },
    { key: "battery", label: "Battery (V)", keys: ["battery_v"], column: "battery_v" },
  ].filter((v) => ordered.some((m) => v.keys.some((k) => m.columns.includes(k))));
  const pages = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
  const visible = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const show = (index: number) => window.dispatchEvent(
    new CustomEvent<JumpDetail>(JUMP_EVENT, { detail: { table, index } }));

  // Everything one span says, computed once for the table and the cards.
  const spans = visible.map((m, i) => {
    const span: ReadingRow[] = [];
    for (let k = m.start; k <= m.end; k++) {
      const r = byIndex.get(k);
      if (r) span.push(r);
    }
    const prev = i > 0 ? visible[i - 1] : page > 0 ? ordered[page * PAGE_SIZE - 1] : null;
    const later = prev && m.tStart !== null && prev.tEnd !== null ? m.tStart - prev.tEnd : null;
    const firstRow = span[0];
    const points = [...new Set(span.map((r) => r.point_id).filter(Boolean))] as string[];
    const x = mean(span, "x_m"), y = mean(span, "y_m");
    const where = points.length ? points.join(", ")
      : x !== null && y !== null ? `${x.toFixed(2)}, ${y.toFixed(2)}` : "—";
    const values = VALUES.map((v) => ({
      key: v.key, label: v.label,
      text: v.keys.some((k) => m.columns.includes(k)) ? range(span, v.column, 2) ?? "—" : "",
    }));
    const at = client && typeof firstRow?.recorded_at === "string"
      ? formatLocal(firstRow.recorded_at, "time") : "—";
    const into = m.tStart !== null && m.tEnd !== null
      ? (Math.round(m.tStart) === Math.round(m.tEnd) ? clock(m.tStart) : `${clock(m.tStart)}–${clock(m.tEnd)}`)
      : "—";
    const count = m.end - m.start + 1;
    const readings = m.start === m.end ? `#${m.start}` : `#${m.start}–${m.end}`;
    return { m, later, where, values, at, into, readings, count };
  });
  const gap = (later: number | null) => later !== null && later > 0.5
    ? (later >= 1 ? `${Math.round(later).toLocaleString()} s later` : "moments later") : null;
  const chip = (m: Mark) => (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-sm border-l-[3px] px-1.5 py-0.5"
          style={{ borderLeftColor: groupColor(m.group), background: groupTint(m.group, m.severity) }}>
      <MarkShape mark={m} />
      <span>{shortLabel(m)} · {SEVERITY[m.severity].label}</span>
    </span>
  );
  const showButton = (m: Mark) => (
    <button type="button" onClick={() => show(m.start)}
            className="inline-flex h-7 items-center rounded border border-[var(--border)] px-2 hover:bg-[var(--surface-2)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">
      Show<span className="sr-only">{" "}readings {m.start} to {m.end}</span>
    </button>
  );
  const cell = "px-2 py-1.5 align-top";

  return (
    <div className="space-y-3">
      {/* Wide screens: a table that fits — fixed column widths, one line per
          fact, only "What happened" wraps; nothing scrolls sideways. */}
      <div className="hidden overflow-hidden rounded-lg border border-[var(--border)] xl:block">
        <table className="w-full table-fixed border-collapse text-left text-xs">
          <caption className="sr-only">
            What went wrong, in time order: {ordered.length} spans, {visible.length} on this page.
          </caption>
          <colgroup>
            <col className="w-[5.75rem]" />
            <col className="w-[6.25rem]" />
            <col className="w-[7.5rem]" />
            <col className="w-[6.5rem]" />
            <col className="w-[10.5rem]" />
            <col />
            {VALUES.map((v) => <col key={v.key} className="w-[6.5rem]" />)}
            <col className="w-[4rem]" />
          </colgroup>
          <thead className="bg-[var(--surface-2)]">
            <tr className="text-[11px] uppercase tracking-wide">
              <th scope="col" className="px-2 py-2 font-semibold">Time</th>
              <th scope="col" className="px-2 py-2 font-semibold">Into {what}</th>
              <th scope="col" className="px-2 py-2 font-semibold">Readings</th>
              <th scope="col" className="px-2 py-2 font-semibold">Where</th>
              <th scope="col" className="px-2 py-2 font-semibold">Data</th>
              <th scope="col" className="px-2 py-2 font-semibold">What happened</th>
              {VALUES.map((v) => (
                <th key={v.key} scope="col" className="px-2 py-2 text-right font-semibold">{v.label}</th>
              ))}
              <th scope="col" className="px-2 py-2"><span className="sr-only">Show the readings</span></th>
            </tr>
          </thead>
          <tbody>
            {spans.map(({ m, later, where, values, at, into, readings, count }) => [
              gap(later) && (
                <tr key={`${m.id}-gap`} aria-hidden="true">
                  <td colSpan={7 + VALUES.length}
                      className="border-t border-dashed border-[var(--border)] px-2 py-0.5 text-center text-[11px] text-[var(--muted)]">
                    {gap(later)}
                  </td>
                </tr>
              ),
              <tr key={m.id} className="border-t border-[var(--border)] hover:bg-[var(--surface-2)]">
                <th scope="row" className={`${cell} whitespace-nowrap font-medium`}>{at}</th>
                <td className={`${cell} tabular whitespace-nowrap`}>{into}</td>
                <td className={`${cell} tabular whitespace-nowrap`}>
                  {readings} <span className="text-[var(--muted)]">({count})</span>
                </td>
                <td className={`${cell} tabular whitespace-nowrap`}>{where}</td>
                <td className={cell}>{chip(m)}</td>
                <td className={`${cell} leading-snug [overflow-wrap:anywhere]`}>
                  <span className="font-semibold">{m.title}.</span> {m.body}
                </td>
                {values.map((v) => (
                  <td key={v.key} className={`${cell} tabular whitespace-nowrap text-right`}>{v.text}</td>
                ))}
                <td className={`${cell} text-right`}>{showButton(m)}</td>
              </tr>,
            ])}
          </tbody>
        </table>
      </div>

      {/* Narrow screens: the same spans as cards — nothing to scroll. */}
      <ol className="grid gap-2 xl:hidden" aria-label="What went wrong, in time order">
        {spans.map(({ m, later, where, values, at, into, readings, count }) => (
          <li key={m.id} className="grid gap-2">
            {gap(later) && (
              <p aria-hidden="true" className="text-center text-[11px] text-[var(--muted)]">{gap(later)}</p>
            )}
            <article className="grid gap-1.5 rounded-lg border border-[var(--border)] border-l-4 bg-[var(--surface)] p-3 text-xs"
                     style={{ borderLeftColor: groupColor(m.group) }}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                {chip(m)}
                <span className="text-[var(--muted)]">{m.kind === "anomaly" ? "anomaly" : "flagged"}</span>
              </div>
              <p><span className="font-semibold">{m.title}.</span> {m.body}</p>
              <p className="text-[var(--muted)]">
                {[at, `${into} into the ${what}`, `${readings} (${count} reading${count === 1 ? "" : "s"})`,
                  where !== "—" ? where : null].filter(Boolean).join(" · ")}
              </p>
              {values.some((v) => v.text) && (
                <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                  {values.filter((v) => v.text).map((v) => (
                    <div key={v.key} className="contents">
                      <dt className="text-[var(--muted)]">{v.label}</dt>
                      <dd className="tabular text-right">{v.text}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <div>{showButton(m)}</div>
            </article>
          </li>
        ))}
      </ol>
      {pages > 1 && (
        <nav aria-label="Error pages" className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p className="text-[var(--muted)]" aria-live="polite">
            {page * PAGE_SIZE + 1}–{Math.min(ordered.length, (page + 1) * PAGE_SIZE)} of {ordered.length} · page {page + 1} of {pages}
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={() => setPage((p) => p - 1)} disabled={page === 0}
                    className="min-h-11 rounded-md border border-[var(--border)] px-4 disabled:opacity-50">Previous</button>
            <button type="button" onClick={() => setPage((p) => p + 1)} disabled={page >= pages - 1}
                    className="min-h-11 rounded-md border border-[var(--border)] px-4 disabled:opacity-50">Next</button>
          </div>
        </nav>
      )}
    </div>
  );
}
