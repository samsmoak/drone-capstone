import { getFlightTelemetry, getRunningFlight, getZones } from "@/lib/queries";
import { PageHeader } from "@/components/ui/page-header";
import { LiveView } from "@/components/live-view";
import { LocalTime } from "@/components/ui/local-time";

export const metadata = { title: "Live" };

export default async function LivePage() {
  const [flight, zones] = await Promise.all([getRunningFlight(), getZones()]);
  // The readings so far are read on the server, so the page opens mid-flight
  // with the whole track drawn instead of starting from the next packet.
  const initial = flight ? await getFlightTelemetry(flight.id) : [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Live"
        description={
          flight ? (
            <>
              Flight started <LocalTime iso={flight.started_at} />. Readings arrive from the agent
              as they are recorded.
            </>
          ) : (
            "Telemetry from the drone as it flies."
          )
        }
      />
      <LiveView flight={flight} initial={initial} zones={zones} />
    </div>
  );
}
