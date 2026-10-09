import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getEnhancedFrames,
  getFindings,
  getFlightsTelemetry,
  getPipelineResults,
  getSession,
  getSessionFlights,
  getSessionFrames,
  type TelemetryRow,
} from "@/lib/queries";
import { FindingsList, type FrameLinks } from "@/components/processing/findings";
import { FlightProcessing } from "@/components/processing/flight-processing";
import { FrameGallery } from "@/components/flight/FrameGallery";
import { RawReadings } from "@/components/ui/raw-readings";
import { Stat, StatusBadge } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { LocalTime } from "@/components/ui/local-time";
import { OwnerStat } from "@/components/ui/owner";
import { FLIGHTS, PROCESSED, SESSIONS } from "@/lib/routes";
import {
  SEVERITY,
  excerptsFor,
  frameMarks,
  highlightsOf,
  readFrames,
  readTracks,
  severityOf,
} from "@/lib/pipeline";

export const metadata = { title: "Processed data · session" };

/**
 * One session's processed data: its anomalies with their readings, frames and
 * meaning; then each processed flight — what ran, a verdict per point, raw vs
 * clean against what was expected with the anomalous stretches shaded, and
 * every reading with those stretches tinted (hover for what they mean); then
 * the camera, the frames taken during an anomaly outlined.
 *
 * The session page (app/app/sessions/[id]) still holds everything in the
 * session; this is the pipeline's view of it.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm">{children}</p>
  );
}

export default async function ProcessedSessionPage(props: PageProps<"/app/processed/[id]">) {
  const { id } = await props.params;
  if (!UUID.test(id)) notFound();

  const [session, flights, frames, enhanced] = await Promise.all([
    getSession(id),
    getSessionFlights(id),
    getSessionFrames(id),
    getEnhancedFrames(id),
  ]);
  if (!session) notFound();
  const flightIds = flights.map((f) => f.id);
  const [results, findings, telemetry] = await Promise.all([
    getPipelineResults(flightIds),
    getFindings(flightIds),
    getFlightsTelemetry(flightIds),
  ]);
  const resultOf = new Map(results.rows.map((r) => [r.flight_id, r]));
  const processed = flights.filter((f) => resultOf.has(f.id));
  const notProcessed = flights.filter((f) => !resultOf.has(f.id));
  const flightNumber = new Map(flights.map((f, i) => [f.id, i + 1]));

  // Each anomaly's readings come from its flight's telemetry, already read.
  const readings: Record<string, TelemetryRow[]> = Object.fromEntries(findings.rows.map((f) => [
    f.id, (telemetry[f.flight_id] ?? []).filter((r) => r.index >= f.start_index && r.index <= f.end_index),
  ]));
  const excerpts = excerptsFor(findings.rows,
    (flightId) => readTracks(resultOf.get(flightId)?.tracks ?? []), readings);
  const frameLinks: FrameLinks = Object.fromEntries(
    frames.map((f) => [f.seq, { original: f.url, enhanced: enhanced[f.seq] }]));
  const marks = frameMarks(findings.rows);
  const enhancedCount = results.rows.reduce((n, r) => n + readFrames(r.frames).filter((f) => f.enhanced).length, 0);
  const bySeverity = (s: string) => findings.rows.filter((f) => severityOf(f.severity) === s).length;

  return (
    <div className="space-y-10">
      <div className="space-y-4">
        <p className="flex flex-wrap gap-x-6 text-sm">
          <Link href={PROCESSED} className="inline-flex min-h-11 items-center underline underline-offset-4">
            ← Processed data
          </Link>
          <Link href={`${SESSIONS}/${id}`} className="inline-flex min-h-11 items-center underline underline-offset-4">
            The whole session →
          </Link>
        </p>
        <PageHeader
          title={<>Processed data · <LocalTime iso={session.started_at} /></>}
          description="What the data pipeline made of this session's flights."
        />
      </div>

      <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Flights processed" value={`${processed.length} of ${flights.length}`} />
        <Stat label="Anomalies" value={findings.rows.length
          ? `${findings.rows.length} · ${bySeverity("critical")} critical, ${bySeverity("warning")} warning`
          : "None"} />
        <Stat label="Frames enhanced" value={`${enhancedCount} of ${frames.length}`} />
        <OwnerStat label="Run by" who={session} />
      </section>

      {!results.migrated || !findings.migrated ? (
        <Note>
          Pipeline results are not on the web yet: the database has no pipeline tables. Apply
          migration 20261009000016_pipeline_results.sql.
        </Note>
      ) : processed.length === 0 ? (
        <Note>
          None of this session&apos;s {flights.length} flight{flights.length === 1 ? " has" : "s have"} been
          processed. Leave Process flights (DPP) on at the top of the desktop app&apos;s Control page,
          or press Process this flight there; the result uploads here.
        </Note>
      ) : (
        <>
          <section aria-labelledby="anomalies-heading" className="space-y-3">
            <h2 id="anomalies-heading" className="text-lg font-semibold text-[var(--heading)]">
              Anomalies in this session
            </h2>
            {findings.rows.length === 0 ? (
              <Note>
                Nothing departed from what was expected in the {processed.length} processed flight
                {processed.length === 1 ? "" : "s"}. The readings below are cleaned and checked; there is
                simply nothing to flag.
              </Note>
            ) : (
              <FindingsList
                findings={findings.rows}
                frames={frameLinks}
                excerpts={excerpts}
                flightOf={(flightId) => flightNumber.has(flightId)
                  ? { label: `Flight ${flightNumber.get(flightId)}`, href: `#flight-${flightId}` }
                  : undefined}
              />
            )}
          </section>

          {processed.map((f) => {
            const mine = findings.rows.filter((x) => x.flight_id === f.id);
            const r = resultOf.get(f.id)!;
            const sev = r.worst_severity ? SEVERITY[severityOf(r.worst_severity)] : null;
            return (
              <section key={f.id} id={`flight-${f.id}`} aria-labelledby={`flight-${f.id}-heading`}
                       className="scroll-mt-24 space-y-6 border-t border-[var(--border)] pt-6">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h2 id={`flight-${f.id}-heading`} className="text-lg font-semibold text-[var(--heading)]">
                    Flight {flightNumber.get(f.id)}{" "}
                    <span className="text-base font-normal text-[var(--muted)]">
                      · <LocalTime iso={f.started_at} /> · {f.program ?? f.mode ?? "flight"}
                    </span>
                  </h2>
                  <span className="flex flex-wrap items-center gap-4">
                    {sev ? <StatusBadge status={sev.status} label={`${mine.length} anomal${mine.length === 1 ? "y" : "ies"} · worst ${sev.label.toLowerCase()}`} />
                      : <StatusBadge status="good" label="No anomalies" />}
                    <Link href={`${FLIGHTS}/${f.id}`} className="inline-flex min-h-11 items-center text-sm underline underline-offset-4">
                      Flight page
                    </Link>
                  </span>
                </div>
                <FlightProcessing result={r} telemetry={telemetry[f.id] ?? []} findings={mine} />
                <div className="space-y-3">
                  <h3 className="text-base font-semibold">Every reading</h3>
                  <RawReadings rows={telemetry[f.id] ?? []} unit={f.temp_unit} highlights={highlightsOf(mine)} />
                </div>
              </section>
            );
          })}

          {notProcessed.length > 0 && (
            <Note>
              Not processed: {notProcessed.map((f) => `Flight ${flightNumber.get(f.id)}`).join(", ")} — flown
              with Process flights (DPP) off, or still waiting. Press Process this flight in the desktop
              app to add {notProcessed.length === 1 ? "it" : "them"}.
            </Note>
          )}
        </>
      )}

      <section aria-labelledby="camera-heading" className="space-y-3">
        <h2 id="camera-heading" className="text-lg font-semibold text-[var(--heading)]">Camera</h2>
        <FrameGallery frames={frames} enhanced={enhanced} marks={marks} />
      </section>
    </div>
  );
}
