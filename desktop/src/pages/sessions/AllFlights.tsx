/**
 * ALL FLIGHTS — every flight that can be played back: this laptop's and
 * everyone's in Supabase, each once (GET /history/flights, agent
 * playback.list_flights). Sessions › All flights.
 *
 * A flight on this laptop plays from here — instant, complete, offline — and
 * says how far its upload has got; every other one plays from Supabase:
 * anyone's, and this account's from another computer or after the files here
 * were deleted. Signed out or offline, this laptop's flights still list, and
 * a line says why the rest do not.
 *
 * Filters by person and by mode. Mode starts on the sidebar's Auto/Manual
 * toggle, like every history view, and can be widened to both.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentError, api, type FlightList, type FlightListItem, type Mode } from "@/lib/agent";
import { formatDateTime, formatTime } from "@/lib/format";
import { Button, Message, Panel, StatusDot } from "@/components/ui";
import { LoadState, MODE_LABEL, type Load } from "./parts";

function who(f: FlightListItem): string {
  return f.operator_name && f.operator_name !== f.operator_email
    ? f.operator_name
    : f.operator_email ?? "Unknown";
}

/** What a flight is called: its program, or its mode. */
export function flightTitle(f: Pick<FlightListItem, "program" | "mode">): string {
  return f.program ?? (f.mode === "manual" ? "Manual flight" : "Program");
}

function Where({ f }: { f: FlightListItem }) {
  if (!f.on_this_computer) return <StatusDot tone="idle">In Supabase</StatusDot>;
  if (f.upload === "uploading") return <StatusDot tone="warning">On this computer · uploading</StatusDot>;
  if (f.in_supabase || f.upload === "uploaded") return <StatusDot tone="good">On this computer · uploaded</StatusDot>;
  return <StatusDot tone="idle">On this computer</StatusDot>;
}

// PARITY: desktop/src/pages/sessions/parts.tsx
// SessionRow's layout — time, who and what, outcome — for one flight, with
// Play back instead of opening a session.
function FlightRow({ f, onPlay }: { f: FlightListItem; onPlay: (f: FlightListItem) => void }) {
  return (
    // By the list's own width (design/layout.txt), not the window's: four
    // columns in a wide list; stacked in a narrow one, where four squeezed an
    // email to "gmail.c / om" at 720 px (measured 2026-10-11).
    <li className="grid items-center gap-x-6 gap-y-2 px-4 py-2.5 @3xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(0,1fr)_auto]">
      <span className="min-w-0">
        <span className="mono block text-sm font-semibold">{formatDateTime(f.started_at)}</span>
        <span className="mono block text-xs text-[var(--muted)]">
          {f.ended_at ? `to ${formatTime(f.ended_at)}` : "No end recorded"}
        </span>
      </span>
      <span className="min-w-0 text-sm">
        <span className="block wrap-anywhere">{who(f)}</span>
        <span className="block wrap-anywhere text-[var(--muted)]">
          {flightTitle(f)}
          {f.mode ? ` · ${MODE_LABEL[f.mode as Mode] ?? f.mode}` : ""}
          {f.has_plan ? " · plan kept" : ""}
        </span>
      </span>
      <span className="min-w-0 text-sm">
        <Where f={f} />
        <span className="block text-[var(--muted)]">
          {f.abort_reason ? `Aborted: ${f.abort_reason.replace(/_/g, " ")}` : (f.outcome ?? "completed").replace(/_/g, " ")}
        </span>
      </span>
      <span><Button onClick={() => onPlay(f)} title="Watch this flight again on the room map">Play back</Button></span>
    </li>
  );
}

export function AllFlights({ refreshKey, mode, onPlay }: {
  refreshKey: unknown;
  mode: Mode;
  onPlay: (f: FlightListItem) => void;
}) {
  const [allModes, setAllModes] = useState(false);
  const [person, setPerson] = useState<string>("");
  const [state, setState] = useState<Load<FlightList>>({ kind: "loading" });
  const filter = allModes ? undefined : mode;

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", data: await api.flights(filter) });
    } catch (e) {
      setState({ kind: "error", message: e instanceof AgentError ? e.message : "Could not load the flights." });
    }
  }, [filter]);
  useEffect(() => { void load(); }, [load, refreshKey]);

  const people = useMemo(() => {
    if (state.kind !== "ready") return [];
    return [...new Set(state.data.flights.map(who))].sort((a, b) => a.localeCompare(b));
  }, [state]);
  const shown = state.kind === "ready" ? state.data.flights.filter((f) => !person || who(f) === person) : [];

  return (
    <Panel
      title={allModes ? "All flights" : `${MODE_LABEL[mode]} flights`}
      action={<Button onClick={() => void load()}>Refresh</Button>}
      bodyClassName="grid gap-3 px-4 py-3"
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">
          Who flew it
          <select value={person} onChange={(e) => setPerson(e.target.value)}
                  className="min-h-11 w-full min-w-0 border border-[var(--border)] bg-[var(--surface)] px-2 text-sm text-[var(--foreground)]">
            <option value="">Everyone</option>
            {people.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="inline-flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" checked={allModes} onChange={(e) => setAllModes(e.target.checked)}
                 className="h-5 w-5" />
          Both modes (Auto and Manual)
        </label>
      </div>

      {state.kind === "ready" && state.data.cloud === "signed_out" && (
        <Message tone="warning" text="Signed out: only this computer's flights are listed. Sign in to see everyone's flights from Supabase." />
      )}
      {state.kind === "ready" && state.data.cloud === "error" && (
        <div className="grid gap-2">
          <Message tone="warning" text={`Supabase could not be reached, so only this computer's flights are listed. ${state.data.cloud_error ?? ""}`} />
          <div><Button onClick={() => void load()}>Try again</Button></div>
        </div>
      )}

      <LoadState
        state={state}
        reload={() => void load()}
        loadingLabel="Loading the flights…"
        empty={state.kind === "ready" && shown.length === 0}
        emptyText={<p>{person ? `No flights by ${person}` : "No flights yet"}{allModes ? "." : ` in ${MODE_LABEL[mode]}. Tick Both modes to see the rest.`}</p>}
      >
        {() => (
          <div className="@container -mx-4">
            <ul className="divide-y divide-[var(--border)]" aria-label="Flights, newest first">
              {shown.map((f) => <FlightRow key={f.id} f={f} onPlay={onPlay} />)}
            </ul>
          </div>
        )}
      </LoadState>
    </Panel>
  );
}
