import Link from "next/link";
import { getDashboardSummary } from "@/lib/queries";
import { EmptyState, Stat } from "@/components/ui/states";
import { FLIGHTS, PLAN, SETUP } from "@/lib/routes";
import { batteryStatus } from "@/lib/flight-format";
import { LocalTime } from "@/components/ui/local-time";

export const metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const summary = await getDashboardSummary();
  const { latest, telemetry } = summary;

  const lastRow = telemetry.at(-1) ?? null;
  const battery = lastRow?.battery_v ?? null;
  const unit = latest?.temp_unit ?? "C";

  if (!latest) {
    return (
      <EmptyState
        title="No flights recorded yet"
        hint="Once the drone completes a flight, its telemetry appears here."
        action={
          <Link
            href={SETUP}
            className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
          >
            Set up the system
          </Link>
        }
      />
    );
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--heading)]">Dashboard</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Last flight{" "}
            <LocalTime iso={latest.started_at} />
          </p>
        </div>
        <Link
          href={PLAN}
          className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
        >
          Plan a mission
        </Link>
      </header>

      <section
        aria-label="Latest readings"
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <Stat
          label="Battery"
          value={battery !== null ? battery.toFixed(2) : null}
          unit="V"
          status={batteryStatus(battery)}
          hint={
            battery !== null && battery < 3.75
              ? "Below the arming threshold"
              : undefined
          }
        />
        <Stat
          label={`Temperature (${unit})`}
          value={
            lastRow?.corrected_temp != null
              ? lastRow.corrected_temp.toFixed(1)
              : null
          }
          unit={`°${unit}`}
          hint="Corrected for onboard heat"
        />
        <Stat
          label="Pressure"
          value={
            lastRow?.station_pressure_hpa != null
              ? lastRow.station_pressure_hpa.toFixed(1)
              : null
          }
          unit="hPa"
        />
        <Stat label="Samples" value={summary.sampleCount} hint="This flight" />
      </section>

      <section
        aria-label="System"
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <Stat label="Flights recorded" value={summary.flightCount} />
        <Stat label="Zones mapped" value={summary.zoneCount} />
        <Stat
          label="Missions queued"
          value={summary.queued}
          hint={summary.queued > 0 ? "Waiting for the agent" : undefined}
        />
        <Stat label="Flight status" value={latest.status} />
      </section>

      <p className="text-sm">
        <Link href={FLIGHTS} className="underline underline-offset-4">
          See all flights
        </Link>
      </p>
    </div>
  );
}
