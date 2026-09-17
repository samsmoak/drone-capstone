/**
 * The session history, read from this laptop.
 *
 * Three views over the same records:
 *
 *   RecentSessions   the last few, on the Control page — who, when, how it went
 *   SessionsPage     every session, and one session's full detail
 *   WindowLog        one sensor window's readings, one collapsible section per
 *                    session, so a long history is opened only where needed
 *
 * Everything is scoped to a session: the person who ran it and the time range
 * it covered. Readings load when a section is opened, not all at once.
 *
 * All three follow the Auto/Manual toggle. The mode is filtered per reading,
 * not per session, because a session can switch mode between flights — a
 * session that used both appears under both, showing only that mode's readings.
 */

const MODE_LABEL: Record<Mode, string> = { auto: "Auto", manual: "Manual" };

function ModeNote({ mode }: { mode: Mode }) {
  return (
    <p className="text-sm text-[var(--muted)]">
      Showing <strong className="text-[var(--foreground)]">{MODE_LABEL[mode]}</strong> data only — switch
      Auto/Manual at the top to see the other.
    </p>
  );
}

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AgentError, api, type Mode, type SampleRow, type SessionRecord } from "./agent";
import {
  endReasonLabel,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatTime,
} from "./format";
import { Button, Message, PageHeader, Panel, Spinner, Stat, StatusDot } from "./ui";
import { WINDOWS, WINDOW_VARIABLES, type Variable, type WindowKey } from "./windows";

// ── data ─────────────────────────────────────────────────────────────

type Load<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: T };

function useSessions(limit: number, refreshKey: unknown, mode: Mode) {
  const [state, setState] = useState<Load<SessionRecord[]>>({ kind: "loading" });
  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", data: await api.listSessions(limit, mode) });
    } catch (e) {
      setState({ kind: "error", message: e instanceof AgentError ? e.message : "Could not load sessions." });
    }
  }, [limit, mode]);
  // refreshKey: reload when a session starts or ends.
  useEffect(() => { void load(); }, [load, refreshKey]);
  return { state, reload: load };
}

// ── pieces ───────────────────────────────────────────────────────────

/**
 * A disclosure whose contents mount only once opened.
 *
 * React renders a closed <details>' children anyway, so a plain one would
 * fetch every session's readings the moment the list appeared. This mounts the
 * body on first open and keeps it, so reopening does not refetch.
 */
function Disclosure({ summary, summaryClassName, children }: {
  summary: ReactNode;
  summaryClassName: string;
  children: () => ReactNode;
}) {
  const [opened, setOpened] = useState(false);
  return (
    <details
      className="group rounded-xl border border-[var(--border)] bg-[var(--surface)]"
      onToggle={(e) => { if (e.currentTarget.open) setOpened(true); }}
    >
      <summary className={summaryClassName}>{summary}</summary>
      {opened && <div className="border-t border-[var(--border)] px-5 py-4">{children()}</div>}
    </details>
  );
}

function Who({ record }: { record: SessionRecord }) {
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

function SessionRow({ record, onOpen }: { record: SessionRecord; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="grid w-full gap-x-6 gap-y-1 rounded-lg px-4 py-3 text-left transition-colors hover:bg-[var(--surface-2)] sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto]"
      >
        <span className="min-w-0">
          <span className="block font-medium">{formatDateTime(record.started_at)}</span>
          <span className="block text-sm text-[var(--muted)]">
            {record.ended_at ? `to ${formatTime(record.ended_at)} · ${formatDuration(record.duration_s)}` : "Still running"}
          </span>
        </span>
        <span className="min-w-0 text-sm">
          <Who record={record} />
          <span className="block text-[var(--muted)]">
            {record.mode === "auto" ? "Auto" : "Manual"}
            {!record.assisted && " · unassisted"}
            {` · ${record.flights.length} flight${record.flights.length === 1 ? "" : "s"}`}
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

function LoadState<T>({ state, reload, empty, children }: {
  state: Load<T>;
  reload: () => void;
  empty: boolean;
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
  if (empty) {
    return (
      <p className="text-sm text-[var(--muted)]">
        No sessions in this mode on this computer yet. Start one from Control — it will be listed
        here with who ran it and when.
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

// ── recent sessions (Control page) ───────────────────────────────────

export function RecentSessions({ refreshKey, mode, onOpen, onOpenAll }: {
  refreshKey: unknown;
  mode: Mode;
  onOpen: (id: string) => void;
  onOpenAll: () => void;
}) {
  const { state, reload } = useSessions(5, refreshKey, mode);
  return (
    <Panel
      title={`Recent ${MODE_LABEL[mode]} sessions`}
      note="Kept on this computer, online or not. Follows the Auto/Manual toggle."
      action={<Button onClick={onOpenAll}>All sessions →</Button>}
    >
      <LoadState state={state} reload={reload} empty={state.kind === "ready" && state.data.length === 0}>
        {(records) => (
          <ul className="-mx-4 divide-y divide-[var(--border)]">
            {records.map((r) => <SessionRow key={r.id} record={r} onOpen={() => onOpen(r.id)} />)}
          </ul>
        )}
      </LoadState>
    </Panel>
  );
}

// ── sessions page ────────────────────────────────────────────────────

export function SessionsPage({ refreshKey, mode, selectedId, onSelect }: {
  refreshKey: unknown;
  mode: Mode;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const { state, reload } = useSessions(200, refreshKey, mode);

  if (selectedId) {
    return <SessionDetail id={selectedId} mode={mode} onBack={() => onSelect(null)} />;
  }

  return (
    <div className="grid gap-6">
      <PageHeader title={`${MODE_LABEL[mode]} sessions`}>
        Every session run on this computer: who ran it, when it started and ended, and what the
        drone reported. Open one for its flights and readings.
      </PageHeader>
      <ModeNote mode={mode} />
      <Panel title="All sessions" action={<Button onClick={reload}>Refresh</Button>}>
        <LoadState state={state} reload={reload} empty={state.kind === "ready" && state.data.length === 0}>
          {(records) => (
            <ul className="-mx-4 divide-y divide-[var(--border)]">
              {records.map((r) => <SessionRow key={r.id} record={r} onOpen={() => onSelect(r.id)} />)}
            </ul>
          )}
        </LoadState>
      </Panel>
    </div>
  );
}

function SessionDetail({ id, mode, onBack }: { id: string; mode: Mode; onBack: () => void }) {
  const [state, setState] = useState<Load<SessionRecord>>({ kind: "loading" });
  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", data: await api.readSession(id) });
    } catch (e) {
      setState({ kind: "error", message: e instanceof AgentError ? e.message : "Could not load this session." });
    }
  }, [id]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="grid gap-6">
      <div>
        <button type="button" onClick={onBack} className="text-sm font-medium text-[var(--muted)] hover:text-[var(--foreground)]">
          ← All sessions
        </button>
      </div>
      {state.kind === "loading" && <Spinner label="Loading the session…" />}
      {state.kind === "error" && (
        <div className="grid gap-3">
          <Message tone="critical" text={state.message} />
          <div><Button onClick={() => void load()}>Try again</Button></div>
        </div>
      )}
      {state.kind === "ready" && <SessionDetailBody record={state.data} mode={mode} />}
    </div>
  );
}

function SessionDetailBody({ record, mode }: { record: SessionRecord; mode: Mode }) {
  const s = record.summary;
  return (
    <>
      <PageHeader title={`Session · ${formatDateTime(record.started_at)}`}>
        Run by {record.operator_name && record.operator_name !== record.operator_email
          ? `${record.operator_name} (${record.operator_email})`
          : record.operator_email}{" "}
        on drone {record.drone_hardware_id ?? "unknown"}.
      </PageHeader>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Started" value={formatTime(record.started_at)} />
        <Stat label="Ended" value={record.ended_at ? formatTime(record.ended_at) : "Running"}
              hint={endReasonLabel(record.end_reason)} />
        <Stat label="Duration" value={formatDuration(record.duration_s)} />
        <Stat label="Flights" value={String(record.flights.length)}
              hint={`${record.mode === "auto" ? "Auto" : "Manual"}${record.assisted ? "" : " · unassisted"}`} />
      </section>
      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Battery start" value={s.battery_start_v} unit="V" />
        <Stat label="Battery lowest" value={s.battery_min_v} unit="V" />
        <Stat label="Highest" value={s.max_height_m} unit="m" hint="Above the floor at takeoff" />
        <Stat label="Temperature" value={s.temp_min_c != null ? `${formatNumber(s.temp_min_c, 1)}–${formatNumber(s.temp_max_c, 1)}` : null}
              unit="°C" hint="Raw sensor range" />
      </section>

      <ModeNote mode={mode} />

      <Panel title={`${MODE_LABEL[mode]} flights`}>
        {record.flights.filter((f) => f.mode === mode).length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No {MODE_LABEL[mode].toLowerCase()} flights in this session.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {record.flights.filter((f) => f.mode === mode).map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
                <span>
                  <span className="font-medium">{f.program ?? (f.mode === "manual" ? "Manual flight" : "Program")}</span>
                  <span className="block text-[var(--muted)]">
                    {formatTime(f.started_at)} – {formatTime(f.ended_at)}
                  </span>
                </span>
                {f.abort_reason
                  ? <StatusDot tone="warning">Aborted: {f.abort_reason.replace(/_/g, " ")}</StatusDot>
                  : <StatusDot tone="good">{(f.outcome ?? "completed").replace(/_/g, " ")}</StatusDot>}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {WINDOWS.map((w) => (
        <Disclosure
          key={w.key}
          summaryClassName="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4"
          summary={
            <>
              <span className="font-medium text-[var(--heading)]">{w.label} readings</span>
              <span aria-hidden="true" className="text-[var(--muted)] transition-transform group-open:rotate-90">›</span>
            </>
          }
        >
          {() => <ReadingsTable sessionId={record.id} variables={WINDOW_VARIABLES[w.key]} mode={mode} />}
        </Disclosure>
      ))}
    </>
  );
}

// ── one window's log across sessions ─────────────────────────────────

export function WindowLog({ windowKey, refreshKey, mode, onBack }: {
  windowKey: WindowKey;
  refreshKey: unknown;
  mode: Mode;
  onBack: () => void;
}) {
  const page = WINDOWS.find((w) => w.key === windowKey)!;
  const { state, reload } = useSessions(200, refreshKey, mode);

  return (
    <div className="grid gap-6">
      <div>
        <button type="button" onClick={onBack} className="text-sm font-medium text-[var(--muted)] hover:text-[var(--foreground)]">
          ← Live {page.label.toLowerCase()}
        </button>
      </div>
      <PageHeader title={`${page.label} log · ${MODE_LABEL[mode]}`}>
        Every {page.label.toLowerCase()} reading, grouped by session — each one scoped to the person who
        ran it and the time it ran. Open a session to see its readings.
      </PageHeader>
      <ModeNote mode={mode} />
      <LoadState state={state} reload={reload} empty={state.kind === "ready" && state.data.length === 0}>
        {(records) => (
          <div className="grid gap-3">
            {records.map((r) => (
              <Disclosure
                key={r.id}
                summaryClassName="grid cursor-pointer list-none gap-1 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center"
                summary={
                  <>
                    <span>
                      <span className="block font-medium">{formatDateTime(r.started_at)}</span>
                      <span className="block text-sm text-[var(--muted)]">
                        <Who record={r} /> · {r.ended_at ? formatDuration(r.duration_s) : "running"}
                      </span>
                    </span>
                    <span className="text-sm text-[var(--muted)]">
                      <span className="group-open:hidden">Show readings ›</span>
                      <span className="hidden group-open:inline">Hide readings</span>
                    </span>
                  </>
                }
              >
                {() => <ReadingsTable sessionId={r.id} variables={WINDOW_VARIABLES[windowKey]} mode={mode} />}
              </Disclosure>
            ))}
          </div>
        )}
      </LoadState>
    </div>
  );
}

/** A time-stamped table of readings, fetched when its section is first opened. */
function ReadingsTable({ sessionId, variables, mode }: { sessionId: string; variables: Variable[]; mode: Mode }) {
  const [state, setState] = useState<Load<SampleRow[]>>({ kind: "loading" });
  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", data: await api.readSamples(sessionId, variables.map((v) => v.name), mode) });
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
    return <p className="text-sm text-[var(--muted)]">No {MODE_LABEL[mode].toLowerCase()} readings were recorded in this session.</p>;
  }
  return (
    <div className="max-h-[28rem] overflow-auto rounded-lg border border-[var(--border)]">
      <table className="w-full text-sm">
        <caption className="sr-only">Readings, one per second</caption>
        <thead className="sticky top-0 bg-[var(--surface-2)]">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">Time</th>
            {variables.map((v) => (
              <th key={v.name} scope="col" className="px-3 py-2 text-right font-medium">
                {v.label}{v.unit ? <span className="font-normal text-[var(--muted)]"> {v.unit}</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">
          {state.data.map((row, i) => (
            <tr key={`${row.recorded_at}-${i}`}>
              <td className="tabular whitespace-nowrap px-3 py-1.5">{formatTime(row.recorded_at)}</td>
              {variables.map((v) => {
                const raw = row[v.name];
                const num = typeof raw === "number" ? raw : null;
                return (
                  <td key={v.name} className="tabular px-3 py-1.5 text-right">
                    {formatNumber(num, v.digits ?? 2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
