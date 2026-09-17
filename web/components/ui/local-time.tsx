"use client";

import { useSyncExternalStore } from "react";

/**
 * A timestamp in the viewer's own timezone.
 *
 * `toLocaleString()` in a Server Component formats in the *server's* timezone.
 * On Vercel that is UTC, so a flight at 4:45 PM Eastern rendered as 8:45 PM
 * with nothing to say so — correct-looking and wrong. Only the browser knows
 * the operator's timezone, so formatting happens there.
 *
 * Before hydration the server renders UTC and says it is UTC, so the first
 * paint is never a wrong local-looking time.
 */

export type TimeFormat = "datetime" | "time" | "short";

const noop = () => () => {};

/** True once running in the browser; false during the server render and hydration. */
export function useIsClient(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}

export function formatLocal(iso: string, format: TimeFormat): string {
  const date = new Date(iso);
  switch (format) {
    case "datetime":
      return date.toLocaleString();
    case "time":
      return date.toLocaleTimeString();
    case "short":
      return date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    default: {
      const unhandled: never = format;
      return unhandled;
    }
  }
}

function formatUtc(iso: string, format: TimeFormat): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  if (format === "time") return `${time}:${pad(d.getUTCSeconds())} UTC`;
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${time} UTC`;
}

export function LocalTime({ iso, format = "datetime" }: { iso: string; format?: TimeFormat }) {
  const client = useIsClient();
  return (
    <time dateTime={iso} suppressHydrationWarning>
      {client ? formatLocal(iso, format) : formatUtc(iso, format)}
    </time>
  );
}
