"use client";

import { useMemo, useState } from "react";
import { formatLocal, useIsClient } from "@/components/ui/local-time";
import { MarkShape } from "@/components/ui/mark-legend";
import { JUMP_EVENT, type JumpDetail } from "@/components/ui/raw-readings";
import { GROUPS, SEVERITY, clock, groupColor, groupTint, type Mark } from "@/lib/pipeline";

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

  // Only the value columns some span is about — never a column of blanks.
  const VALUES = [
    { key: "temp", label: `Temp`, keys: ["raw_temp", "corrected_temp"] },
    { key: "pressure", label: "Pressure (hPa)", keys: ["station_pressure_hpa"] },
    { key: "position", label: "Position (m)", keys: ["x_m", "y_m", "z_m"] },
    { key: "battery", label: "Battery (V)", keys: ["battery_v"] },
  ].filter((v) => ordered.some((m) => v.keys.some((k) => m.columns.includes(k))));
  const pages = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
  const visible = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const sym = unit === "F" ? "°F" : "°C";
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
    const x = mean(span, "x_m"), y = mean(span, "y_m"), z = mean(span, "z_m");
    const where = points.length ? points.join(", ")
      : x !== null && y !== null ? `(${x.toFixed(2)}, ${y.toFixed(2)})${z !== null ? `, z ${z.toFixed(2)}` : ""}`
        : null;
    const about = (keys: string[]) => keys.some((k) => m.columns.includes(k));
    const value = (keys: string[], key: string) => (about(keys) ? range(span, key, 2) ?? "—" : "");
    const values = VALUES.map((v) => ({
      key: v.key, label: v.key === "temp" ? `Temp (${sym})` : v.label,
      text: v.key === "temp" ? value(v.keys, "raw_temp")
        : v.key === "pressure" ? value(v.keys, "station_pressure_hpa")
          : v.key === "position" ? (about(v.keys) && x !== null && y !== null
            ? `${x.toFixed(2)}, ${y.toFixed(2)}, ${(z ?? 0).toFixed(2)}` : about(v.keys) ? "—" : "")
            : value(v.keys, "battery_v"),
    }));
    const at = client && typeof firstRow?.recorded_at === "string"
      ? formatLocal(firstRow.recorded_at, "time") : null;
    const clockRange = m.tStart !== null && m.tEnd !== null
      ? `${clock(m.tStart)}–${clock(m.tEnd)} · ${Math.max(0, Math.round(m.tEnd - m.tStart))} s` : null;
    const readingsText = m.start === m.end ? `#${m.start} · 1 reading`
      : `#${m.start}–${m.end} · ${m.end - m.start + 1} readings`;
    return { m, later, where, values, at, clockRange, readingsText };
  });
  const gap = (later: number | null) => later !== null && later > 0.5
    ? (later >= 1 ? `${Math.round(later).toLocaleString()} s later` : "moments later") : null;
  const chip = (m: Mark) => (
    <span className="inline-flex items-center gap-1.5 rounded border-l-4 px-2 py-1"
          style={{ borderLeftColor: groupColor(m.group), background: groupTint(m.group, m.severity) }}>
      <MarkShape mark={m} />
      <span>{GROUPS[m.group].label} · {SEVERITY[m.severity].label}</span>
    </span>
  );
  const showButton = (m: Mark) => (
    <button type="button" onClick={() => show(m.start)}
            className="mt-1 inline-flex min-h-11 items-center rounded-md border border-[var(--border)] px-3 hover:bg-[var(--surface-2)]">
      Show<span className="sr-only">{" "}readings {m.start} to {m.end}</span>
    </button>
  );

  return (
    <div className="space-y-3">
      {/* Wide screens: a table that fits — fixed column widths, the words
          wrap, nothing scrolls sideways. */}
      <div className="hidden rounded-lg border border-[var(--border)] xl:block">
        <table className="w-full table-fixed border-collapse text-left text-xs">
          <caption className="sr-only">
            What went wrong, in time order: {ordered.length} spans, {visible.length} on this page.
          </caption>
          <colgroup>
            <col className="w-40" />
            <col className="w-44" />
            <col />
            {VALUES.map((v) => <col key={v.key} className="w-24" />)}
          </colgroup>
          <thead className="bg-[var(--surface-2)]">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">When · where</th>
              <th scope="col" className="px-3 py-2 font-medium">Data</th>
              <th scope="col" className="px-3 py-2 font-medium">What happened</th>
              {VALUES.map((v) => (
                <th key={v.key} scope="col" className="px-3 py-2 text-right font-medium">
                  {v.key === "temp" ? `Temp (${sym})` : v.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {spans.map(({ m, later, where, values, at, clockRange, readingsText }) => [
              gap(later) && (
                <tr key={`${m.id}-gap`} aria-hidden="true">
                  <td colSpan={3 + VALUES.length} className="border-t border-dashed border-[var(--border)] px-3 py-1 text-center text-[11px] text-[var(--muted)]">
                    {gap(later)}
                  </td>
                </tr>
              ),
              <tr key={m.id} className="border-t border-[var(--border)] align-top">
                <th scope="row" className="px-3 py-2 font-normal">
                  {at && <span className="block font-medium">{at}</span>}
                  {clockRange && <span className="block text-[var(--muted)]">{clockRange}</span>}
                  <span className="tabular block">{readingsText}</span>
                  {where && <span className="block text-[var(--muted)]">{where}</span>}
                  {showButton(m)}
                </th>
                <td className="px-3 py-2">
                  {chip(m)}
                  <span className="block pt-1 text-[var(--muted)]">{m.kind === "anomaly" ? "anomaly" : "flagged"}</span>
                </td>
                <td className="px-3 py-2 [overflow-wrap:anywhere]">
                  <span className="font-semibold">{m.title}.</span> {m.body}
                </td>
                {values.map((v) => (
                  <td key={v.key} className="tabular px-3 py-2 text-right [overflow-wrap:anywhere]">{v.text}</td>
                ))}
              </tr>,
            ])}
          </tbody>
        </table>
      </div>

      {/* Narrow screens: the same spans as cards — nothing to scroll. */}
      <ol className="grid gap-2 xl:hidden" aria-label="What went wrong, in time order">
        {spans.map(({ m, later, where, values, at, clockRange, readingsText }) => (
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
                {[at, clockRange, readingsText, where].filter(Boolean).join(" · ")}
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
