/**
 * Formatting shared by the history views.
 *
 * Times are stored as UTC ISO strings and always shown in this computer's own
 * time zone — the operator reads "14:02", not "18:02Z".
 */

const dateTime = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
});
const timeOnly = new Intl.DateTimeFormat(undefined, {
  hour: "numeric", minute: "2-digit", second: "2-digit",
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : dateTime.format(date);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : timeOnly.format(date);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "In progress";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function formatNumber(value: number | null | undefined, digits = 2, unit = ""): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

/** An end reason in the words an operator would use. */
export function endReasonLabel(reason: string | null | undefined): string {
  switch (reason) {
    case null:
    case undefined:
      return "Still running";
    case "operator":
      return "Ended by the operator";
    case "battery_low":
      return "Battery ran low";
    case "signed out":
      return "Signed out";
    case "agent shutting down":
      return "App closed";
    default:
      return reason.replace(/_/g, " ");
  }
}

export function initialOf(name: string | null | undefined, email: string | null | undefined): string {
  const source = (name || email || "?").trim();
  return source.charAt(0).toUpperCase() || "?";
}
