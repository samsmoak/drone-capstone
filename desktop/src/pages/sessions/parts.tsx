/**
 * The pieces the three session views share.
 *
 * Everything is scoped to a session: the person who ran it and the time range it
 * covered. Readings load when a section is opened, not all at once.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AgentError, api, type Mode, type SampleRow, type SessionRecord } from "@/lib/agent";
import { endReasonLabel, formatDateTime, formatDuration, formatNumber, formatTime } from "@/lib/format";
import { openDashboard } from "@/lib/web";
import { Button, Message, Spinner, StatusDot } from "@/components/ui";
import type { Variable } from "@/pages/windows/SensorWindow";

export const MODE_LABEL: Record<Mode, string> = { auto: "Auto", manual: "Manual" };
export const OTHER_MODE: Record<Mode, Mode> = { auto: "manual", manual: "auto" };

export type Load<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: T };

/**
 * Sessions in a mode, and how many exist in the other one.
 *
 * The count matters: the toggle defaults to Auto, and an operator whose flights
 * were all manual saw "no sessions" with 45 readings sitting on disk. The views
 * offer those instead of pretending there is nothing.
 */
export function useSessions(limit: number, refreshKey: unknown, mode: Mode | null) {
  const [state, setState] = useState<Load<SessionRecord[]>>({ kind: "loading" });
  const [hidden, setHidden] = useState(0);

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const [shown, all] = await Promise.all([
        api.listSessions(limit, mode ?? undefined),
        mode ? api.listSessions(limit) : Promise.resolve<SessionRecord[]>([]),
      ]);
      setHidden(mode ? all.length - shown.length : 0);
      setState({ kind: "ready", data: shown });
    } catch (e) {
      setState({ kind: "error", message: e instanceof AgentError ? e.message : "Could not load sessions." });
    }
  }, [limit, mode]);

  useEffect(() => { void load(); }, [load, refreshKey]);
  return { state, hidden, reload: load };
}

export function Who({ record }: { record: SessionRecord }) {
  return (
    <span className="wrap-anywhere">
      {record.operator_name && record.operator_name !== record.operator_email
        ? record.operator_name
        : record.operator_email}
    </span>
  );
}

function Outcome({ record }: { record: SessionRecord }) {
  const aborted = record.flights.some((f) => f.abort_reason);
  if (!record.ended_at) return <StatusDot tone="good">Running now</StatusDot>;
  if (record.end_reason === "battery_low") return <StatusDot tone="warning">Battery ran low</StatusDot>;
  if (aborted) return <StatusDot tone="warning">Flight aborted</StatusDot>;
  return <StatusDot tone="idle">{endReasonLabel(record.end_reason)}</StatusDot>;
}

export function SessionRow({ record, onOpen }: { record: SessionRecord; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="grid w-full gap-x-6 gap-y-1 px-4 py-2.5 text-left transition-colors hover:bg-[var(--surface-2)] sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto]"
      >
        <span className="min-w-0">
          {/* Times and durations are figures: monospace, so a column of rows
              lines up on the digits instead of drifting. */}
          <span className="mono block text-sm font-semibold">{formatDateTime(record.started_at)}</span>
          <span className="mono block text-xs text-[var(--muted)]">
            {record.ended_at
              ? `to ${formatTime(record.ended_at)} · ${formatDuration(record.duration_s)}`
              : "Still running"}
          </span>
        </span>
        <span className="min-w-0 text-sm">
          <Who record={record} />
          <span className="block text-[var(--muted)]">
            {MODE_LABEL[record.mode as Mode] ?? record.mode}
            {!record.assisted && " · unassisted"}
            {` · ${record.summary.samples} readings`}
          </span>
        </span>
        <span className="text-sm sm:text-right">
          <Outcome record={record} />
          <span className="tabular block text-[var(--muted)]">
            {record.summary.battery_start_v != null
              ? `${formatNumber(record.summary.battery_start_v)} → ${formatNumber(record.summary.battery_end_v)} V`
              : "No readings"}
          </span>
        </span>
      </button>
    </li>
  );
}

/** "2 Manual sessions are hidden" — with the one click that shows them. */
export function HiddenByMode({ mode, hidden, onShowAll }: {
  mode: Mode;
  hidden: number;
  onShowAll: () => void;
}) {
  if (hidden <= 0) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-[var(--status-warning)] bg-[var(--surface)] px-4 py-3 text-sm">
      <StatusDot tone="warning">
        {hidden} {MODE_LABEL[OTHER_MODE[mode]].toLowerCase()} session{hidden === 1 ? " is" : "s are"} hidden
        by the {MODE_LABEL[mode]} toggle.
      </StatusDot>
      <button type="button" onClick={onShowAll} className="font-semibold underline underline-offset-2">
        Show every session
      </button>
    </p>
  );
}

/** Where to go for more than this laptop recorded. */
export function DashboardLink({ path = "/app/flights", children }: { path?: string; children?: ReactNode }) {
  return (
    <Button onClick={() => void openDashboard(path)}>
      {children ?? "Open the dashboard"} ↗
    </Button>
  );
}

export function LoadState<T>({ state, reload, empty, emptyText, children }: {
  state: Load<T>;
  reload: () => void;
  empty: boolean;
  emptyText: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (state.kind === "loading") return <Spinner label="Loading sessions…" />;
  if (state.kind === "error") {
    return (
      <div className="grid gap-3">
        <Message tone="critical" text={state.message} />
        <div><Button onClick={reload}>Try again</Button></div>
      </div>
    );
  }
  if (empty) return <div className="text-sm text-[var(--muted)]">{emptyText}</div>;
  return <>{children(state.data)}</>;
}

/**
 * A disclosure whose contents mount only once opened.
 *
 * React renders a closed <details>' children anyway, so a plain one would fetch
 * every session's readings the moment the list appeared.
 */
export function Disclosure({ summary, summaryClassName, children, open = false }: {
  summary: ReactNode;
  summaryClassName: string;
  children: () => ReactNode;
  /** Open from the start: a log the operator asked to see should not need a
   *  second click to show anything. */
  open?: boolean;
}) {
  const [opened, setOpened] = useState(open);
  // Opened once, on mount. Held as a prop instead, React would reopen it on
  // every re-render and the operator could never close it.
  const started = useRef(false);
  return (
    <details
      ref={(el) => {
        if (el && open && !started.current) {
          started.current = true;
          el.open = true;
        }
      }}
      className="group rounded-xl border border-[var(--border)] bg-[var(--surface)]"
      onToggle={(e) => { if (e.currentTarget.open) setOpened(true); }}
    >
      <summary className={summaryClassName}>{summary}</summary>
      {opened && <div className="border-t border-[var(--border)] px-5 py-4">{children()}</div>}
    </details>
  );
}

/** A time-stamped table of readings, fetched when its section is first opened. */
/** Rows shown per session in a log. The rest are a click away in the dashboard. */
export const READINGS_SHOWN = 25;

export function ReadingsTable({ sessionId, variables, mode, limit = READINGS_SHOWN }: {
  sessionId: string;
  variables: Variable[];
  mode: Mode | null;
  limit?: number;
}) {
  const [state, setState] = useState<Load<SampleRow[]>>({ kind: "loading" });
  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const rows = await api.readSamples(sessionId, variables.map((v) => v.name), mode ?? undefined);
      setState({ kind: "ready", data: rows });
    } catch (e) {
      setState({ kind: "error", message: e instanceof AgentError ? e.message : "Could not load the readings." });
    }
  }, [sessionId, variables, mode]);
  useEffect(() => { void load(); }, [load]);

  if (state.kind === "loading") return <Spinner label="Loading readings…" />;
  if (state.kind === "error") {
    return (
      <div className="grid gap-3">
        <Message tone="critical" text={state.message} />
        <div><Button onClick={() => void load()}>Try again</Button></div>
      </div>
    );
  }
  if (state.data.length === 0) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No readings were recorded in this session{mode ? ` in ${MODE_LABEL[mode].toLowerCase()} mode` : ""}.
      </p>
    );
  }
  // The latest readings: what happened most recently is what is asked about.
  const rows = state.data.slice(-limit);
  return (
    <div className="grid gap-2">
      {state.data.length > rows.length && (
        // Above the table, not below it: inside the scroll box the operator
        // would have to reach the end to learn there was more.
        <p className="text-xs text-[var(--muted)]">
          The latest {rows.length} of {state.data.length} readings — the dashboard has them all.
        </p>
      )}
      {/* Denser than a page table, because this IS a readout: every cell is a
          figure, and the scroll box shows more of them per screen this way. */}
      <div className="console-scroll max-h-[28rem] overflow-auto border border-[var(--border)]">
        <table className="w-full text-xs">
          <caption className="sr-only">Readings, one per second</caption>
          <thead className="sticky top-0 bg-[var(--surface-2)]">
            <tr>
              <th scope="col" className="px-3 py-1.5 text-left font-semibold">Time</th>
              {variables.map((v) => (
                <th key={v.name} scope="col" className="px-3 py-1.5 text-right font-semibold">
                  {v.label}
                  {v.unit ? <span className="font-normal text-[var(--muted)]"> {v.unit}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="mono divide-y divide-[var(--border)]">
            {rows.map((row, i) => (
              <tr key={`${row.recorded_at}-${i}`}>
                <td className="whitespace-nowrap px-3 py-1">{formatTime(row.recorded_at)}</td>
                {variables.map((v) => {
                  const raw = row[v.name];
                  return (
                    <td key={v.name} className="px-3 py-1 text-right">
                      {formatNumber(typeof raw === "number" ? raw : null, v.digits ?? 2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
