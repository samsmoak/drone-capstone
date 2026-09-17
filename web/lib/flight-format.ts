import type { FlightRow } from "@/lib/queries";

/**
 * Presentation helpers shared by the flight pages. No I/O, so they are safe on
 * either side of the server/client boundary.
 */

/** A flight's status as one of the four reserved status tones. */
export function flightTone(
  status: FlightRow["status"],
): "good" | "warning" | "serious" | "critical" {
  switch (status) {
    case "completed":
      return "good";
    case "running":
      return "warning";
    case "aborted":
      return "serious";
    case "failed":
      return "critical";
    default: {
      // Exhaustive: a new enum value in the schema is a compile error here,
      // not a flight silently shown as healthy.
      const unhandled: never = status;
      return unhandled;
    }
  }
}

/** Voltage thresholds, from what the firmware actually does. */
export function batteryStatus(v: number | null): "good" | "warning" | "critical" | undefined {
  if (v === null) return undefined;
  if (v < 3.3) return "critical";
  // Below roughly 3.75 V the supervisor refuses to arm at all, so "will not
  // fly" is a more useful warning than a percentage.
  if (v < 3.75) return "warning";
  return "good";
}

/** A flight status as a sentence-case word for a badge: "completed" → "Completed". */
export function flightStatusLabel(status: FlightRow["status"]): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

/** "1 m 24 s", or "in progress" / "—" when there is no end. */
export function flightDuration(startedAt: string, endedAt: string | null): string {
  if (!endedAt) return "in progress";
  const seconds = Math.round((Date.parse(endedAt) - Date.parse(startedAt)) / 1000);
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m} m ${s} s` : `${s} s`;
}

/** Seconds since the first sample, which is what a flight chart's x-axis wants. */
export function elapsedSeconds(recordedAt: string, firstRecordedAt: string): number {
  return (Date.parse(recordedAt) - Date.parse(firstRecordedAt)) / 1000;
}

/**
 * Metres → feet, for labels only.
 *
 * CLAUDE.md: metres everywhere internally; feet appear only in UI labels,
 * converted at the boundary. Nothing that is stored or compared uses this.
 */
export function metresToFeet(m: number): number {
  return m * 3.28084;
}
