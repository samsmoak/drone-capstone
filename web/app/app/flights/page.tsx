import Link from "next/link";
import { getRecentFlights } from "@/lib/queries";
import { EmptyState, StatusBadge } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { FLIGHTS, PLAN } from "@/lib/routes";
import { flightDuration, flightStatusLabel, flightTone } from "@/lib/flight-format";
import { LocalTime } from "@/components/ui/local-time";

export const metadata = { title: "Flights" };

export default async function FlightsPage() {
  const flights = await getRecentFlights(50);

  if (flights.length === 0) {
    return (
      <div className="space-y-8">
        <PageHeader title="Flights" description="Every flight the agent has recorded." />
        <EmptyState
          title="No flights recorded yet"
          hint="Flights appear here as soon as the agent completes one and uploads its telemetry."
          action={
            <Link
              href={PLAN}
              className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
            >
              Plan a mission
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Flights"
        description="Every flight the agent has recorded, newest first."
      />

      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            Recorded flights, newest first
          </caption>
          <thead className="bg-[var(--surface-2)]">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Started</th>
              <th scope="col" className="px-4 py-3 font-medium">Status</th>
              <th scope="col" className="px-4 py-3 font-medium">Duration</th>
              <th scope="col" className="px-4 py-3 font-medium">Ambient</th>
              <th scope="col" className="px-4 py-3 font-medium">Ground</th>
              <th scope="col" className="px-4 py-3 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {flights.map((flight) => (
              <tr key={flight.id} className="border-t border-[var(--border)]">
                <th scope="row" className="px-4 py-3 font-normal">
                  <LocalTime iso={flight.started_at} />
                </th>
                <td className="px-4 py-3">
                  {/* Icon + word. A failed flight must not be signalled by
                      colour alone. */}
                  <StatusBadge
                    status={flightTone(flight.status)}
                    label={flightStatusLabel(flight.status)}
                  />
                </td>
                <td className="tabular px-4 py-3">
                  {flightDuration(flight.started_at, flight.ended_at)}
                </td>
                <td className="tabular px-4 py-3">
                  {flight.ambient_start != null
                    ? `${flight.ambient_start.toFixed(1)}°${flight.temp_unit}`
                    : "—"}
                </td>
                <td className="tabular px-4 py-3">
                  {/* Lighthouse z = 0 is not the floor, so the captured ground
                      reference is worth showing: it explains an altitude that
                      looks wrong. */}
                  {flight.ground_z_m != null ? `${flight.ground_z_m.toFixed(3)} m` : "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={`${FLIGHTS}/${flight.id}`}
                    className="inline-flex min-h-11 items-center underline underline-offset-4"
                  >
                    Open<span className="sr-only">
                      {" "}flight from <LocalTime iso={flight.started_at} />
                    </span>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
