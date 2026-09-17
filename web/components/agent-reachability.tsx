"use client";

import { useCallback, useEffect, useState } from "react";

const AGENT_URL = process.env.NEXT_PUBLIC_AGENT_URL ?? "http://127.0.0.1:8765";

type AgentStatus = {
  drone_connected: boolean;
  uri: string | null;
  busy: boolean;
  current: string | null;
  manual_state: string | null;
};

type State =
  | { kind: "checking" }
  | { kind: "absent" }
  | { kind: "running"; status: AgentStatus | null; checkedAt: Date };

/**
 * Whether the agent is reachable from this browser, and what it can see.
 *
 * Asks the agent itself (`/health`, then `/status`) rather than inferring from
 * anything stored — the running system is the authority. `/status` scans the
 * radio, which takes a moment, so it is checked on demand, not polled.
 */
export function AgentReachability() {
  const [state, setState] = useState<State>({ kind: "checking" });

  const check = useCallback(async () => {
    setState({ kind: "checking" });
    try {
      const health = await fetch(`${AGENT_URL}/health`, { signal: AbortSignal.timeout(2000) });
      if (!health.ok) throw new Error();
    } catch {
      setState({ kind: "absent" });
      return;
    }
    try {
      const response = await fetch(`${AGENT_URL}/status`, { signal: AbortSignal.timeout(8000) });
      const status = response.ok ? ((await response.json()) as AgentStatus) : null;
      setState({ kind: "running", status, checkedAt: new Date() });
    } catch {
      setState({ kind: "running", status: null, checkedAt: new Date() });
    }
  }, []);

  useEffect(() => {
    // Checking on mount is the point of the panel; the result lands asynchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void check();
  }, [check]);

  const rows: { label: string; value: string; tone?: "good" | "warning" | "critical" }[] =
    state.kind === "checking"
      ? []
      : state.kind === "absent"
        ? [{ label: "Agent", value: "Not reachable from this browser", tone: "critical" }]
        : [
            { label: "Agent", value: `Running at ${AGENT_URL}`, tone: "good" },
            ...(state.status
              ? [
                  {
                    label: "Radio and drone",
                    value: state.status.drone_connected
                      ? `Found at ${state.status.uri ?? "unknown URI"}`
                      : "No drone found — radio plugged in, battery connected, powered on?",
                    tone: state.status.drone_connected ? ("good" as const) : ("warning" as const),
                  },
                  {
                    label: "Activity",
                    value: state.status.busy ? `Busy: ${state.status.current ?? "flying"}` : "Idle",
                  },
                ]
              : [{ label: "Radio and drone", value: "The agent did not report its status", tone: "warning" as const }]),
          ];

  const icon = { good: "●", warning: "▲", critical: "■" } as const;

  return (
    <div className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5">
      {state.kind === "checking" ? (
        <p role="status" aria-live="polite" className="text-sm text-[var(--muted)]">
          Checking the agent on this computer…
        </p>
      ) : (
        <dl className="space-y-3" role="status" aria-live="polite">
          {rows.map((row) => (
            <div key={row.label} className="grid gap-1 sm:grid-cols-[10rem_1fr]">
              <dt className="text-sm text-[var(--muted)]">{row.label}</dt>
              <dd className="flex items-start gap-2 text-sm font-medium">
                {row.tone && (
                  <span aria-hidden="true" style={{ color: `var(--status-${row.tone})` }}>
                    {icon[row.tone]}
                  </span>
                )}
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {state.kind === "absent" && (
        <p className="text-sm text-[var(--muted)]">
          Start the CropWatcher app on the computer with the radio. If it is running and this
          still fails, the browser may be blocking a web page from reaching this computer — the
          desktop app is not affected.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void check()}
          disabled={state.kind === "checking"}
          className="inline-flex min-h-11 items-center rounded-md border border-[var(--border)] px-4 text-sm disabled:opacity-50"
        >
          {state.kind === "checking" ? "Checking…" : "Check again"}
        </button>
        {state.kind === "running" && (
          <span className="text-xs text-[var(--muted)]">
            Checked {state.checkedAt.toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  );
}
