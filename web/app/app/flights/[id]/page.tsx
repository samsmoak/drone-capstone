import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getFlight,
  getFlightTelemetry,
  getPredictionsForFlight,
  getZones,
} from "@/lib/queries";
import { ErrorState, Stat, StatusBadge } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { TimeSeries } from "@/components/ui/time-series";
import { FlightPath } from "@/components/ui/flight-path";
import { RawReadings } from "@/components/ui/raw-readings";
import { FLIGHTS } from "@/lib/routes";
import {
  elapsedSeconds,
  flightDuration,
  flightStatusLabel,
  flightTone,
} from "@/lib/flight-format";
import { LocalTime } from "@/components/ui/local-time";

export const metadata = { title: "Flight" };

/** Matches `getFlightTelemetry`'s default cap. */
const TELEMETRY_CAP = 5000;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function FlightPage(props: PageProps<"/app/flights/[id]">) {
  const { id } = await props.params;

  // A malformed id is a missing page, not a database error: Postgres would
  // reject it as invalid uuid syntax and the operator would see "could not load".
  if (!UUID.test(id)) notFound();

  const [flight, telemetry, zones, predictions] = await Promise.all([
    getFlight(id),
    getFlightTelemetry(id, TELEMETRY_CAP),
    getZones(),
    getPredictionsForFlight(id),
  ]);
  if (!flight) notFound();

  const unit = flight.temp_unit;
  const first = telemetry[0]?.recorded_at;
  // Only the columns the charts use cross into the client bundle.
  const series = telemetry.map((r) => ({
    t: first ? Math.round(elapsedSeconds(r.recorded_at, first) * 10) / 10 : 0,
    raw_temp: r.raw_temp,
    corrected_temp: r.corrected_temp,
    ambient_est: r.ambient_est,
    // `z_m` is already metres above the ground reference captured at takeoff —
    // the agent subtracts it when it writes the row (telemetry/reader.py).
    // Subtracting it again here made every height wrong by the floor's offset.
    height_m: r.z_m,
    battery_v: r.battery_v,
    station_pressure_hpa: r.station_pressure_hpa,
  }));

  return (
    <div className="space-y-10">
      <div className="space-y-4">
        <p className="text-sm">
          <Link href={FLIGHTS} className="inline-flex min-h-11 items-center underline underline-offset-4">
            ← All flights
          </Link>
        </p>
        <PageHeader
          title={
            <>
              Flight · <LocalTime iso={flight.started_at} />
            </>
          }
          description={
            <StatusBadge
              status={flightTone(flight.status)}
              label={flightStatusLabel(flight.status)}
            />
          }
        />
      </div>

      {flight.error && (
        <ErrorState title="This flight did not finish cleanly" detail={flight.error} />
      )}

      {telemetry.length >= TELEMETRY_CAP && (
        <p
          role="status"
          className="rounded-lg border border-[var(--status-warning)] bg-[var(--surface)] p-3 text-sm"
        >
          <span aria-hidden="true">▲ </span>
          Showing the first {TELEMETRY_CAP.toLocaleString()} samples. This flight recorded
          more; the full record is in its CSV{flight.csv_path ? ` (${flight.csv_path})` : ""}.
        </p>
      )}

      <section aria-label="Summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Duration" value={flightDuration(flight.started_at, flight.ended_at)} />
        <Stat label="Samples" value={telemetry.length.toLocaleString()} />
        <Stat
          label="Ambient at launch"
          value={flight.ambient_start != null ? flight.ambient_start.toFixed(1) : null}
          unit={`°${unit}`}
        />
        <Stat
          label="Ground reference"
          value={flight.ground_z_m != null ? flight.ground_z_m.toFixed(3) : null}
          unit="m"
          hint="Lighthouse z captured at takeoff"
        />
      </section>

      <section aria-labelledby="temp-heading" className="space-y-3">
        <h2 id="temp-heading" className="text-lg font-semibold text-[var(--heading)]">
          Temperature (°{unit})
        </h2>
        <p className="text-sm text-[var(--muted)]">
          The raw sensor reads warm because the drone heats it. Corrected is what the
          room actually was.
        </p>
        <TimeSeries
          rows={series}
          xKey="t"
          xLabel="Time (s)"
          xFormat="seconds"
          yLabel={`°${unit}`}
          series={[
            { key: "raw_temp", label: "Raw", slot: 1, unit: `°${unit}` },
            { key: "corrected_temp", label: "Corrected", slot: 2, unit: `°${unit}` },
            { key: "ambient_est", label: "Ambient estimate", slot: 3, unit: `°${unit}` },
          ]}
        />
      </section>

      {/* Different units, so different charts — never a second y-axis. */}
      <div className="grid gap-10 lg:grid-cols-2">
        <section aria-labelledby="alt-heading" className="space-y-3">
          <h2 id="alt-heading" className="text-lg font-semibold text-[var(--heading)]">
            Height above ground (m)
          </h2>
          <TimeSeries
            rows={series}
            xKey="t"
            xLabel="Time (s)"
            xFormat="seconds"
            yLabel="m"
            digits={3}
            series={[{ key: "height_m", label: "Height", slot: 1, unit: "m" }]}
          />
        </section>

        <section aria-labelledby="battery-heading" className="space-y-3">
          <h2 id="battery-heading" className="text-lg font-semibold text-[var(--heading)]">
            Battery (V)
          </h2>
          <TimeSeries
            rows={series}
            xKey="t"
            xLabel="Time (s)"
            xFormat="seconds"
            yLabel="V"
            series={[{ key: "battery_v", label: "Battery", slot: 1, unit: "V" }]}
          />
        </section>

        <section aria-labelledby="pressure-heading" className="space-y-3">
          <h2 id="pressure-heading" className="text-lg font-semibold text-[var(--heading)]">
            Station pressure (hPa)
          </h2>
          <TimeSeries
            rows={series}
            xKey="t"
            xLabel="Time (s)"
            xFormat="seconds"
            yLabel="hPa"
            series={[{ key: "station_pressure_hpa", label: "Pressure", slot: 1, unit: "hPa" }]}
          />
        </section>

        <section aria-labelledby="path-heading" className="space-y-3">
          <h2 id="path-heading" className="text-lg font-semibold text-[var(--heading)]">
            Flight path
          </h2>
          <FlightPath rows={telemetry} zones={zones} />
        </section>
      </div>

      <section aria-labelledby="health-heading" className="space-y-3">
        <h2 id="health-heading" className="text-lg font-semibold text-[var(--heading)]">
          Zone health
        </h2>
        {predictions.length === 0 ? (
          <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
            No health estimates for this flight. Estimates are produced by the agent after
            a flight, once crop-health inference is enabled.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
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

      <section aria-labelledby="raw-heading" className="space-y-3">
        <h2 id="raw-heading" className="text-lg font-semibold text-[var(--heading)]">
          Raw readings
        </h2>
        <RawReadings rows={telemetry} unit={unit} />
      </section>
    </div>
  );
}
