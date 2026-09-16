"use client";

import { useState } from "react";
import type { TelemetryRow } from "@/lib/queries";
import { formatLocal, useIsClient } from "@/components/ui/local-time";

/**
 * Every stored column of every sample, paged.
 *
 * Paged rather than capped: a flight's raw rows are the evidence when a chart
 * looks wrong, and quietly showing only the first N would hide exactly the end
 * of the flight where things usually go wrong.
 */

const PAGE_SIZE = 100;

const COLUMNS: { key: keyof TelemetryRow; label: string; digits?: number }[] = [
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

function cell(row: TelemetryRow, key: keyof TelemetryRow, client: boolean, digits?: number): string {
  const value = row[key];
  if (value === null || value === undefined) return "—";
  // Viewer's timezone once in the browser; an explicit UTC ISO string before.
  if (key === "recorded_at") return client ? formatLocal(String(value), "time") : String(value);
  if (typeof value === "number" && digits !== undefined) return value.toFixed(digits);
  return String(value);
}

export function RawReadings({ rows, unit }: { rows: TelemetryRow[]; unit: string }) {
  const client = useIsClient();
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const visible = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const first = page * PAGE_SIZE + 1;
  const last = Math.min(rows.length, (page + 1) * PAGE_SIZE);

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
        No readings were stored for this flight.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {/* Scrolls inside its own box, header pinned, so a page of readings does
          not push the rest of the flight off the bottom of the screen. The
          region is focusable so it can be scrolled from the keyboard. */}
      <div
        tabIndex={0}
        role="region"
        aria-label="Raw readings table"
        className="max-h-[32rem] overflow-auto rounded-lg border border-[var(--border)]"
      >
        <table className="w-full border-collapse text-left text-xs">
          <caption className="sr-only">
            Raw readings {first} to {last} of {rows.length}. Temperatures in °{unit}.
          </caption>
          <thead className="sticky top-0 bg-[var(--surface-2)]">
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} scope="col" className="whitespace-nowrap px-3 py-2 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.id} className="border-t border-[var(--border)]">
                {COLUMNS.map((c) => (
                  <td key={c.key} className="tabular whitespace-nowrap px-3 py-1.5">
                    {cell(row, c.key, client, c.digits)}
                  </td>
                ))}
              </tr>
            ))}
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
    </div>
  );
}
