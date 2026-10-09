import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getPredictionsForFlights,
  getSession,
  getSessionEvents,
  getSessionFlights,
  getSessionFrames,
  getSessionSamples,
  getZones,
} from "@/lib/queries";
import { FrameGallery } from "@/components/flight/FrameGallery";
import { Stat, StatusBadge } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { TimeSeries } from "@/components/ui/time-series";
import { FlightPath } from "@/components/ui/flight-path";
import { RawReadings, type ReadingColumn } from "@/components/ui/raw-readings";
import { FLIGHTS, SESSIONS } from "@/lib/routes";
import {
  elapsedSeconds,
  flightDuration,
  flightStatusLabel,
  flightTone,
} from "@/lib/flight-format";
import { LocalTime } from "@/components/ui/local-time";
import { Owner, OwnerStat } from "@/components/ui/owner";

export const metadata = { title: "Session" };

/**
 * One session, read like the flight page (app/app/flights/[id]) — summary,
 * charts, path, camera, zone health, raw readings — over the session's OWN
 * vitals (session_samples: one a second, Start to End session, flying or
 * not), plus what only a session has: its flights and its events.
 *
 * PARITY: web/app/app/flights/[id]/page.tsx
 */

/** Matches `getSessionSamples`' default cap: 10 000 s, about 2¾ hours. */
const SAMPLE_CAP = 10000;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The session's own samples — their columns, not a flight's. */
const SAMPLE_COLUMNS: ReadingColumn[] = [
  { key: "seq", label: "#" },
  { key: "recorded_at", label: "Recorded" },
  { key: "mode", label: "Mode" },
  { key: "positioned", label: "Positioned" },
  { key: "x_m", label: "x (m)", digits: 3 },
  { key: "y_m", label: "y (m)", digits: 3 },
  { key: "z_m", label: "z (m)", digits: 3 },
  { key: "height_m", label: "Height (m)", digits: 3 },
  { key: "battery_v", label: "Battery (V)", digits: 2 },
  { key: "thrust", label: "Thrust", digits: 0 },
  { key: "raw_temp", label: "Sensor temp (°C)", digits: 2 },
  { key: "station_pressure_hpa", label: "Pressure (hPa)", digits: 2 },
  { key: "roll_deg", label: "Roll (°)", digits: 1 },
  { key: "pitch_deg", label: "Pitch (°)", digits: 1 },
  { key: "yaw_deg", label: "Yaw (°)", digits: 1 },
  { key: "lighthouse_received", label: "Stations received" },
];

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
      {children}
    </p>
  );
}

export default async function SessionPage(props: PageProps<"/app/sessions/[id]">) {
  const { id } = await props.params;
  // A malformed id is a missing page, not a database error.
  if (!UUID.test(id)) notFound();

  const [session, samples, flights, events, zones, frames] = await Promise.all([
    getSession(id),
    getSessionSamples(id, SAMPLE_CAP),
    getSessionFlights(id),
    getSessionEvents(id),
    getZones(),
    getSessionFrames(id),
  ]);
  if (!session) notFound();
  const predictions = await getPredictionsForFlights(flights.map((f) => f.id));

  const rows = samples.rows;
  const first = rows[0]?.recorded_at;
  // Only the columns the charts use cross into the client bundle.
  const series = rows.map((r) => ({
    t: first ? Math.round(elapsedSeconds(r.recorded_at, first)) : 0,
    raw_temp: r.raw_temp,
    height_m: r.height_m,
    battery_v: r.battery_v,
    station_pressure_hpa: r.station_pressure_hpa,
  }));
  // A path only from samples the drone trusted: an unmeasured base station
  // gives a drifting estimate, which is not a place (agent position_trusted).
  const path = rows.filter((r) => r.positioned).map((r) => ({ x_m: r.x_m, y_m: r.y_m }));

  const noVitals = !samples.migrated ? (
    <Note>
      Session vitals are not on the web yet: the database has no session_samples table. Apply
      migration 20261006000013_session_samples.sql; the laptop keeps every reading and uploads them
      once it exists.
    </Note>
  ) : rows.length === 0 ? (
    <Note>
      No vitals uploaded for this session yet. The laptop records one sample a second from Start
      session to End session and uploads them when it is online.
    </Note>
  ) : null;

  return (
    <div className="space-y-10">
      <div className="space-y-4">
        <p className="text-sm">
          <Link href={SESSIONS} className="inline-flex min-h-11 items-center underline underline-offset-4">
            ← All sessions
          </Link>
        </p>
        <PageHeader
          title={<>Session · <LocalTime iso={session.started_at} /></>}
          description={
            <StatusBadge status={session.ended_at ? "good" : "warning"}
                         label={session.ended_at ? `Ended${session.end_reason ? ` — ${session.end_reason}` : ""}` : "Open"} />
          }
        />
      </div>

      {rows.length >= SAMPLE_CAP && (
        <p role="status" className="rounded-lg border border-[var(--status-warning)] bg-[var(--surface)] p-3 text-sm">
          <span aria-hidden="true">▲ </span>
          Showing the first {SAMPLE_CAP.toLocaleString()} samples. This session recorded more; the
          full record is samples.csv in the session&apos;s folder on the laptop.
        </p>
      )}

      <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Duration" value={flightDuration(session.started_at, session.ended_at)} />
        <Stat label="Flights" value={String(session.flight_count)} />
        <Stat label="Vitals" value={rows.length.toLocaleString()} hint="one sample a second" />
        <Stat label="Camera frames" value={frames.length.toLocaleString()} />
        <OwnerStat label="Run by" who={session} />
        <Stat label="Drone" value={session.drone} />
        <Stat label="Mode at start" value={session.mode_at_start} />
        <Stat label="Positioned" value={rows.length ? `${Math.round((path.length / rows.length) * 100)}%` : null}
              hint="of samples with a trusted position" />
      </section>

      <section aria-labelledby="temp-heading" className="space-y-3">
        <h2 id="temp-heading" className="text-lg font-semibold text-[var(--heading)]">
          Temperature (°C)
        </h2>
        <p className="text-sm text-[var(--muted)]">
          The barometer&apos;s own sensor, which the drone warms. Corrected room temperatures are
          worked out per flight — open a flight below for them.
        </p>
        {noVitals ?? (
          <TimeSeries rows={series} xKey="t" xLabel="Time (s)" xFormat="seconds" yLabel="°C"
                      series={[{ key: "raw_temp", label: "Sensor", slot: 1, unit: "°C" }]} />
        )}
      </section>

      {/* Different units, so different charts — never a second y-axis. */}
      {!noVitals && (
        <div className="grid gap-10 lg:grid-cols-2">
          <section aria-labelledby="alt-heading" className="space-y-3">
            <h2 id="alt-heading" className="text-lg font-semibold text-[var(--heading)]">
              Height above ground (m)
            </h2>
            <TimeSeries rows={series} xKey="t" xLabel="Time (s)" xFormat="seconds" yLabel="m" digits={3}
                        series={[{ key: "height_m", label: "Height", slot: 1, unit: "m" }]} />
          </section>

          <section aria-labelledby="battery-heading" className="space-y-3">
            <h2 id="battery-heading" className="text-lg font-semibold text-[var(--heading)]">
              Battery (V)
            </h2>
            <TimeSeries rows={series} xKey="t" xLabel="Time (s)" xFormat="seconds" yLabel="V"
                        series={[{ key: "battery_v", label: "Battery", slot: 1, unit: "V" }]} />
          </section>

          <section aria-labelledby="pressure-heading" className="space-y-3">
            <h2 id="pressure-heading" className="text-lg font-semibold text-[var(--heading)]">
              Station pressure (hPa)
            </h2>
            <TimeSeries rows={series} xKey="t" xLabel="Time (s)" xFormat="seconds" yLabel="hPa"
                        series={[{ key: "station_pressure_hpa", label: "Pressure", slot: 1, unit: "hPa" }]} />
          </section>

          <section aria-labelledby="path-heading" className="space-y-3">
            <h2 id="path-heading" className="text-lg font-semibold text-[var(--heading)]">
              Where the drone was
            </h2>
            <FlightPath rows={path} zones={zones} what="session" />
          </section>
        </div>
      )}

      <section aria-labelledby="flights-heading" className="space-y-3">
        <h2 id="flights-heading" className="text-lg font-semibold text-[var(--heading)]">
          Flights in this session
        </h2>
        {flights.length === 0 ? (
          <Note>No flights in this session — the drone stayed on the ground. Its vitals are above.</Note>
        ) : (
          <div className="overflow-x-auto [contain:paint] rounded-lg border border-[var(--border)]">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">Flights in this session, in order</caption>
              <thead className="bg-[var(--surface-2)]">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Started</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="px-4 py-3 font-medium">Duration</th>
                  <th scope="col" className="px-4 py-3 font-medium">What flew</th>
                  <th scope="col" className="px-4 py-3 font-medium">Flown by</th>
                  <th scope="col" className="px-4 py-3 font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {flights.map((f) => (
                  <tr key={f.id} className="border-t border-[var(--border)]">
                    <th scope="row" className="px-4 py-3 font-normal"><LocalTime iso={f.started_at} /></th>
                    <td className="px-4 py-3">
                      <StatusBadge status={flightTone(f.status)} label={flightStatusLabel(f.status)} />
                    </td>
                    <td className="tabular px-4 py-3">{flightDuration(f.started_at, f.ended_at)}</td>
                    <td className="px-4 py-3">{f.program ?? f.mode ?? "—"}{f.abort_reason ? ` · ${f.abort_reason}` : ""}</td>
                    <td className="px-4 py-3"><Owner who={f} /></td>
                    <td className="px-4 py-3 text-right">
                      <Link href={`${FLIGHTS}/${f.id}`} className="inline-flex min-h-11 items-center underline underline-offset-4">
                        Open<span className="sr-only">{" "}flight from <LocalTime iso={f.started_at} /></span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="camera-heading" className="space-y-3">
        <h2 id="camera-heading" className="text-lg font-semibold text-[var(--heading)]">Camera</h2>
        <FrameGallery frames={frames} />
      </section>

      <section aria-labelledby="health-heading" className="space-y-3">
        <h2 id="health-heading" className="text-lg font-semibold text-[var(--heading)]">Zone health</h2>
        {predictions.length === 0 ? (
          <Note>
            No health estimates in this session. Estimates are produced per flight by the agent, once
            the inspection pipeline (clean, classify, interpret) runs on it.
          </Note>
        ) : (
          <div className="overflow-x-auto [contain:paint] rounded-lg border border-[var(--border)]">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-[var(--surface-2)]">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Zone</th>
                  <th scope="col" className="px-4 py-3 font-medium">Health score</th>
                  <th scope="col" className="px-4 py-3 font-medium">Disease risk</th>
                  <th scope="col" className="px-4 py-3 font-medium">Label</th>
                  <th scope="col" className="px-4 py-3 font-medium">Samples</th>
                  <th scope="col" className="px-4 py-3 font-medium">Model</th>
                </tr>
              </thead>
              <tbody>
                {predictions.map((p) => (
                  <tr key={p.id} className="border-t border-[var(--border)]">
                    <th scope="row" className="px-4 py-3 font-normal">
                      {zones.find((z) => z.id === p.zone_id)?.label ?? "Unassigned"}
                    </th>
                    <td className="tabular px-4 py-3">{p.health_score?.toFixed(2) ?? "—"}</td>
                    <td className="tabular px-4 py-3">{p.disease_risk?.toFixed(2) ?? "—"}</td>
                    <td className="px-4 py-3">{p.label ?? "—"}</td>
                    <td className="tabular px-4 py-3">{p.sample_count ?? "—"}</td>
                    <td className="px-4 py-3 text-[var(--muted)]">{p.model}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="events-heading" className="space-y-3">
        <h2 id="events-heading" className="text-lg font-semibold text-[var(--heading)]">What happened</h2>
        {events.length === 0 ? (
          <Note>No events recorded for this session (operators see the audit trail).</Note>
        ) : (
          <div tabIndex={0} role="region" aria-label="Session events"
               className="max-h-[28rem] overflow-auto rounded-lg border border-[var(--border)]">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">Session events, in order</caption>
              <thead className="sticky top-0 bg-[var(--surface-2)]">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">When</th>
                  <th scope="col" className="px-4 py-2 font-medium">What</th>
                  <th scope="col" className="px-4 py-2 font-medium">Result</th>
                  <th scope="col" className="px-4 py-2 font-medium">Who</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className="border-t border-[var(--border)]">
                    <th scope="row" className="whitespace-nowrap px-4 py-2 font-normal"><LocalTime iso={e.occurred_at} /></th>
                    <td className="px-4 py-2">{e.action.replaceAll("_", " ")}</td>
                    <td className="px-4 py-2">
                      <StatusBadge status={e.result === "ok" ? "good" : e.result === "refused" ? "warning" : "critical"}
                                   label={e.result} />
                    </td>
                    <td className="px-4 py-2">{e.actor_email ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="raw-heading" className="space-y-3">
        <h2 id="raw-heading" className="text-lg font-semibold text-[var(--heading)]">Raw readings</h2>
        {noVitals ?? <RawReadings rows={rows} unit="C" columns={SAMPLE_COLUMNS} what="session" />}
      </section>
    </div>
  );
}
