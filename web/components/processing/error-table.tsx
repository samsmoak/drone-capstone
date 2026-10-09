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

  return (
    <div className="space-y-3">
      <div className="relative overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full border-collapse text-left text-xs">
          <caption className="sr-only">
            What went wrong, in time order: {ordered.length} spans, {visible.length} on this page.
          </caption>
          <thead className="bg-[var(--surface-2)]">
            <tr>
              {["When", "Readings", "Where", "Data", "What happened"].map((h) => (
                <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
              ))}
              {VALUES.map((v) => (
                <th key={v.key} scope="col" className="whitespace-nowrap px-3 py-2 text-right font-medium">
                  {v.key === "temp" ? `Temp (${sym})` : v.label}
                </th>
              ))}
              <th scope="col" className="px-3 py-2"><span className="sr-only">Show the readings</span></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((m, i) => {
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
                  : "—";
              const about = (keys: string[]) => keys.some((k) => m.columns.includes(k));
              const value = (keys: string[], key: string, digits: number) =>
                about(keys) ? range(span, key, digits) ?? "—" : "";
              const position = about(["x_m", "y_m", "z_m"]) && x !== null && y !== null
                ? `${x.toFixed(2)}, ${y.toFixed(2)}, ${(z ?? 0).toFixed(2)}` : about(["x_m"]) ? "—" : "";
              return [
                later !== null && later > 0.5 && (
                  <tr key={`${m.id}-gap`} aria-hidden="true">
                    <td colSpan={6 + VALUES.length} className="border-t border-dashed border-[var(--border)] px-3 py-1 text-center text-[11px] text-[var(--muted)]">
                      {later >= 1 ? `${Math.round(later).toLocaleString()} s later` : "moments later"}
                    </td>
                  </tr>
                ),
                <tr key={m.id} className="border-t border-[var(--border)] align-top">
                  <th scope="row" className="whitespace-nowrap px-3 py-2 font-normal">
                    {client && typeof firstRow?.recorded_at === "string" && (
                      <span className="block font-medium">{formatLocal(firstRow.recorded_at, "time")}</span>
                    )}
                    {m.tStart !== null && m.tEnd !== null && (
                      <span className="block text-[var(--muted)]">
                        {clock(m.tStart)}–{clock(m.tEnd)} · {Math.max(0, Math.round(m.tEnd - m.tStart))} s
                      </span>
                    )}
                  </th>
                  <td className="tabular whitespace-nowrap px-3 py-2">
                    {m.start === m.end ? `#${m.start}` : `#${m.start}–${m.end}`}
                    <span className="block text-[var(--muted)]">{m.end - m.start + 1} reading{m.end === m.start ? "" : "s"}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">{where}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span className="inline-flex items-center gap-1.5 rounded border-l-4 px-2 py-1"
                          style={{ borderLeftColor: groupColor(m.group), background: groupTint(m.group, m.severity) }}>
                      <MarkShape mark={m} />
                      <span>{GROUPS[m.group].label} · {SEVERITY[m.severity].label}</span>
                    </span>
                    <span className="block pt-1 text-[var(--muted)]">{m.kind === "anomaly" ? "anomaly" : "flagged"}</span>
                  </td>
                  <td className="min-w-[18rem] px-3 py-2">
                    <span className="font-semibold">{m.title}.</span> {m.body}
                  </td>
                  {VALUES.map((v) => (
                    <td key={v.key} className="tabular whitespace-nowrap px-3 py-2 text-right">
                      {v.key === "temp" ? value(v.keys, "raw_temp", 2)
                        : v.key === "pressure" ? value(v.keys, "station_pressure_hpa", 2)
                          : v.key === "position" ? position : value(v.keys, "battery_v", 2)}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => show(m.start)}
                            className="inline-flex min-h-11 items-center rounded-md border border-[var(--border)] px-3 hover:bg-[var(--surface-2)]">
                      Show<span className="sr-only">{" "}readings {m.start} to {m.end}</span>
                    </button>
                  </td>
                </tr>,
              ];
            })}
          </tbody>
        </table>
      </div>
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
