/**
 * The data pipeline on the Control page: the DPP switch, and the result of
 * the last flight.
 *
 * THE SWITCH IS PER SESSION (backend/agent/cropwatcher/processing.py): on by
 * default in Auto — a mission's point is its verdicts — and off by default in
 * Manual; either can be flipped. It is read as a flight BEGINS, so flipping it
 * mid-flight is for the next one, and the switch says so. The agent keeps the
 * choice; this page only shows it (Session.processing) and asks to change it.
 *
 * THE RESULT has the four states of every async surface here, plus the two
 * the pipeline adds: being processed (queued, running), failed with the
 * pipeline's own words and a way to run it again, not processed (DPP was off)
 * with a way to process it now, and the verdicts — one per inspection point,
 * or one for a Manual flight ("flight") — then the FINDINGS: each stretch of
 * the flight whose temperature or pressure departed from what was expected,
 * worst first, in the pipeline's own words (features/pipeline/
 * data-pipeline.txt). A version 1 result (before 2026-10-09) has none, and
 * one from before the classifier existed reads "no classifier yet" — the panel
 * says so.
 */

import { useCallback, useEffect, useState } from "react";
import type { Run } from "@/App";
import { api, AgentError, type FlightResult, type PipelineFinding, type ProcessingJob, type Session } from "@/lib/agent";
import { formatTime } from "@/lib/format";
import { Button, Message, Panel, Spinner, StatusDot, type Tone } from "@/components/ui";

export function ProcessingSwitch({ session, run }: { session: Session; run: Run }) {
  const on = session.processing?.on ?? false;
  const chosen = session.processing?.chosen ?? false;
  const signedOut = session.state === "signed_out";
  const flying = session.activity === "mission" || session.activity === "manual" || session.activity === "program";
  const mode = session.mode === "auto" ? "Auto" : "Manual";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        disabled={signedOut}
        title={signedOut ? "Sign in first." : undefined}
        onClick={() => void run(() => api.setProcessing(!on), on ? "Turn data processing off" : "Turn data processing on")}
        className="inline-flex min-h-9 items-center gap-2 border border-[var(--border)] bg-[var(--surface)] px-2.5 text-xs font-semibold disabled:opacity-40"
      >
        <span aria-hidden="true"
              className={`relative inline-block h-4 w-7 rounded-full border ${on ? "border-[var(--primary)] bg-[var(--primary)]" : "border-[var(--muted)] bg-[var(--surface-2)]"}`}>
          <span className={`absolute top-0.5 h-2.5 w-2.5 rounded-full ${on ? "left-3.5 bg-[var(--on-primary)]" : "left-0.5 bg-[var(--muted)]"}`} />
        </span>
        Process flights (DPP): {on ? "on" : "off"}
      </button>
      <span className="text-xs text-[var(--muted)]">
        {flying ? "Changes apply to the next flight. " : ""}
        {chosen ? "Your choice for this session." : `${mode}'s default — ${session.mode === "auto" ? "on" : "off"}.`}
      </span>
    </div>
  );
}

/** Which flight to show: the session's most recent flight to land, with its
 *  job if it has one; else the most recent job (a flight processed by hand). */
function lastFlight(session: Session): { id: string; job: ProcessingJob | null } | null {
  const jobs = session.processing?.jobs ?? [];
  const landed = session.processing?.last_flight_id ?? null;
  if (landed) return { id: landed, job: jobs.find((j) => j.flight_id === landed) ?? null };
  return jobs[0] ? { id: jobs[0].flight_id, job: jobs[0] } : null;
}

const SEVERITY: Record<PipelineFinding["severity"], { tone: Tone; text: string; rank: number }> = {
  critical: { tone: "critical", text: "Critical", rank: 2 },
  warning: { tone: "warning", text: "Warning", rank: 1 },
  info: { tone: "idle", text: "Slight", rank: 0 },
};

const VERDICT: Record<string, { tone: Tone; text: string }> = {
  normal: { tone: "good", text: "Normal" },
  anomaly: { tone: "critical", text: "Anomaly" },
  insufficient_data: { tone: "idle", text: "Insufficient data" },
};

export function FlightResults({ session, run, flightId }: { session: Session; run: Run; flightId?: string }) {
  const found = flightId ? { id: flightId, job: session.processing?.jobs?.find((j) => j.flight_id === flightId) ?? null } : lastFlight(session);
  const [result, setResult] = useState<FlightResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const id = found?.id ?? null;
  const state = found?.job?.state ?? null;

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.flightResult(id));
    } catch (e) {
      setResult(null);
      setError(e instanceof AgentError ? e.message : "The result could not be read.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  // Read the result when the flight changes and whenever its job finishes.
  useEffect(() => { if (id && (state === "done" || state === null)) void load(); }, [id, state, load]);

  if (!found) {
    return (
      <p className="text-xs text-[var(--muted)]">
        No flight yet this session. With processing on, each flight is processed when it lands and its verdicts appear here.
      </p>
    );
  }

  const processNow = (
    <Button onClick={() => void run(() => api.processFlight(found.id), "Process this flight")}>
      {state === "failed" || result ? "Process again" : "Process this flight"}
    </Button>
  );

  if (state === "queued" || state === "running") {
    return <Spinner label={state === "queued" ? "Waiting to be processed…" : "Processing this flight…"} />;
  }
  if (state === "failed") {
    return (
      <div className="grid gap-2">
        <Message tone="critical" text={`Processing failed: ${found.job?.error ?? "no reason was given."}`} />
        <div>{processNow}</div>
      </div>
    );
  }
  if (loading && !result) return <Spinner label="Reading the result…" />;
  if (!result) {
    return (
      <div className="grid gap-2">
        <p className="text-xs">{error ?? "This flight has not been processed."}</p>
        <div className="flex flex-wrap gap-2">
          {processNow}
          <Button onClick={() => void load()}>Check again</Button>
        </div>
      </div>
    );
  }

  const r = result.result;
  const placeholder = r.points.every((p) => p.verdict === "insufficient_data"
    && p.reasons.some((why) => why.includes("no classifier yet")));
  return (
    <div className="grid gap-2">
      <p className="mono text-xs text-[var(--muted)]">
        Flight {r.flight_id.slice(0, 8)} · processed {formatTime(r.created_at)} · pipeline {r.pipeline_version}
      </p>
      {placeholder && (
        <Message tone="idle" text="The pipeline ran, but its classify stage is not built yet (the team's work), so every point reads “insufficient data”. The readings and frames below are real." />
      )}
      <ul className="grid gap-1.5">
        {r.points.map((p) => {
          const v = VERDICT[p.verdict] ?? { tone: "idle" as Tone, text: p.verdict };
          const counts = r.summary[p.point_id];
          return (
            <li key={p.point_id} className="grid gap-0.5 border-l-2 border-[var(--border)] pl-2 text-xs">
              <span className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="mono font-semibold">{p.point_id === "flight" ? "The whole flight" : p.point_id}</span>
                <StatusDot tone={v.tone}>{v.text}</StatusDot>
              </span>
              <span className="text-[var(--muted)]">
                {counts?.readings ?? 0} readings · {counts?.frames ?? 0} frames{p.reasons.length ? ` — ${p.reasons.join("; ")}` : ""}
              </span>
            </li>
          );
        })}
      </ul>
      {r.findings && (
        <div className="grid gap-1.5 border-t border-[var(--border)] pt-2">
          <p className="text-xs font-semibold">
            {r.findings.length === 0 ? "No findings — nothing departed from what was expected." : `Findings (${r.findings.length})`}
          </p>
          {r.findings.length > 0 && (
            <ul className="grid gap-1.5">
              {[...r.findings].sort((a, b) => SEVERITY[b.severity].rank - SEVERITY[a.severity].rank || a.t_start_s - b.t_start_s).map((f) => (
                <li key={f.id} className="grid gap-0.5 border-l-2 border-[var(--border)] pl-2 text-xs">
                  <span className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-semibold">{f.title}</span>
                    <StatusDot tone={SEVERITY[f.severity].tone}>{SEVERITY[f.severity].text}</StatusDot>
                  </span>
                  <span>{f.sentence}</span>
                  <span className="text-[var(--muted)]">{f.image_note}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {r.failures.length > 0 && (
        <ul className="grid gap-1">
          {r.failures.map((f, i) => (
            <li key={i} className="text-xs"><StatusDot tone="warning">{`${f.point_id} · ${f.stage}: ${f.reason}`}</StatusDot></li>
          ))}
        </ul>
      )}
      <div>{processNow}</div>
    </div>
  );
}

/** The switch and the last flight's result, as one panel. */
export function DataPipelinePanel({ session, run }: { session: Session; run: Run }) {
  return (
    <Panel title="Data processing" note="Turns a flight's readings and frames into a verdict per inspection point." bodyClassName="grid gap-3 px-4 py-3">
      <ProcessingSwitch session={session} run={run} />
      <div className="border-t border-[var(--border)] pt-3">
        <FlightResults session={session} run={run} />
      </div>
    </Panel>
  );
}
