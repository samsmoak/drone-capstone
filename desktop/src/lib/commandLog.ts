/**
 * What the window did, and what the agent said back.
 *
 * WHAT THIS IS NOT: the audit trail. That one is written BY the agent INTO
 * Supabase (`audit_events`, append-only) against a person and a drone, and the
 * WEB DASHBOARD is what reads it back with filters — see
 * docs/features/backend/audit-trail.txt. It survives a crash and it is the
 * record that counts.
 *
 * The agent offers no local route to read it, so this pane is built entirely
 * from what the window can already see:
 *
 *   - the commands the window itself issues (through App.tsx's `run`)
 *   - the session frames arriving on the live socket
 *
 * It therefore starts when the window opens and is lost when it closes. The
 * pane says so on screen. It exists because during bring-up the window told
 * the operator nothing about what it had just asked the drone to do — the
 * agent's log file was the only record, and reading it meant leaving the app.
 *
 * Nothing here commands anything. It observes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Check, Session } from "@/lib/agent";

export type LogKind =
  | "command"    // the window asked for something
  | "ok"         // it was accepted
  | "refused"    // it was declined, with the agent's own words
  | "state"      // the session moved
  | "check"      // one pre-flight check reported
  | "flight"     // a flight phase changed
  | "link";      // the agent connection came up or went down

export type LogLine = {
  id: number;
  at: number;              // epoch ms, for the gutter stamp
  kind: LogKind;
  text: string;
  detail?: string;
};

/** The glyph in the gutter. Never colour alone — see ui.tsx's own rule. */
export const KIND_GLYPH: Record<LogKind, string> = {
  command: "›",
  ok: "✓",
  refused: "✗",
  state: "—",
  check: "·",
  flight: "▸",
  link: "◇",
};

export const KIND_COLOR: Record<LogKind, string> = {
  command: "var(--console-ink)",
  ok: "var(--status-good)",
  refused: "var(--status-critical)",
  state: "var(--console-dim)",
  check: "var(--console-dim)",
  flight: "var(--primary)",
  link: "var(--status-warning)",
};

/** Lines kept. Beyond this the oldest go: a session is minutes, not hours. */
export const LOG_CAP = 500;

export type Push = (kind: LogKind, text: string, detail?: string) => void;

export function useCommandLog() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const nextId = useRef(0);

  const push = useCallback<Push>((kind, text, detail) => {
    setLines((previous) => {
      const line: LogLine = { id: nextId.current++, at: Date.now(), kind, text, detail };
      const next = [...previous, line];
      return next.length > LOG_CAP ? next.slice(-LOG_CAP) : next;
    });
  }, []);

  const clear = useCallback(() => setLines([]), []);

  return { lines, push, clear };
}

const CHECK_KIND: Record<Check["status"], LogKind> = {
  running: "check",
  passed: "ok",
  warning: "check",
  failed: "refused",
};

/**
 * Turn the session frames into lines — the "order of execution" of a session.
 *
 * Every frame is compared against the one before it and only what changed is
 * written. Pressing Start session therefore reads as the agent's own sequence:
 *
 *   › Start session
 *   — idle → starting
 *   ✓ Radio: cf-4a3b… answered
 *   ✓ Battery: 3.82 V — the drone reports it can fly
 *   ✗ Positioning: only 0 of 4 base stations are being received
 *   — starting → checks_failed
 *
 * which is the thing that was missing: a failed pre-flight you can read in
 * order, in the window, without opening the agent's log file.
 */
export function useSessionNarration(session: Session | null, connected: boolean, push: Push) {
  const previous = useRef<Session | null>(null);
  const wasConnected = useRef<boolean | null>(null);

  useEffect(() => {
    if (wasConnected.current === connected) return;
    // The first frame is the window starting up, not a link event.
    if (wasConnected.current !== null) {
      push("link", connected ? "Flight agent connected" : "Flight agent connection lost");
    }
    wasConnected.current = connected;
  }, [connected, push]);

  useEffect(() => {
    if (!session) return;
    const before = previous.current;
    previous.current = session;

    if (!before) {
      push("link", `Session state: ${session.state}`);
      return;
    }

    if (before.state !== session.state) {
      push("state", `${before.state} → ${session.state}`);
    }

    // Checks, as each one reports. Keyed by `key`, because the agent may append
    // to the list while it works rather than sending them all at once.
    const seen = new Map(before.checks.map((c) => [c.key, c]));
    for (const check of session.checks) {
      const was = seen.get(check.key);
      if (was && was.status === check.status && was.detail === check.detail) continue;
      // "running" with no detail is noise — it says only that a check exists.
      if (check.status === "running" && !check.detail) continue;
      push(CHECK_KIND[check.status], `${check.label}: ${check.status}`, check.detail || undefined);
    }

    if (before.flight?.phase !== session.flight?.phase && session.flight) {
      push("flight", session.flight.phase, session.flight.detail || undefined);
    }

    if (before.health_test !== session.health_test && session.health_test) {
      const result = session.health_test;
      push(
        result.ok ? "ok" : "refused",
        `Battery & motor test: ${result.ok ? "passed" : "did not pass"}`,
        result.motors.failed.length
          ? `Motors ${result.motors.failed.join(", ")} failed`
          : result.battery_error ?? undefined,
      );
    }

    if (before.message !== session.message && session.message) {
      push(session.state === "checks_failed" ? "refused" : "state", session.message);
    }

    if (!before.retry_required && session.retry_required) {
      push("refused", "Retry required — the last flight ended early");
    }
  }, [session, push]);
}
