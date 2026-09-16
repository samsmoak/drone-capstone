import Link from "next/link";
import { getDashboardSummary } from "@/lib/queries";
import { EmptyState, Stat } from "@/components/ui/states";
import { FLIGHTS, PLAN, SETUP } from "@/lib/routes";

export const metadata = { title: "Dashboard" };

/** Voltage thresholds, from what the firmware actually does. */
function batteryStatus(v: number | null): "good" | "warning" | "critical" | undefined {
  if (v === null) return undefined;
  if (v < 3.3) return "critical";
  // Below roughly 3.75 V the supervisor refuses to arm at all, so "will not
  // fly" is a more useful warning than a percentage.
  if (v < 3.75) return "warning";
  return "good";
}

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
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Last flight{" "}
            <time dateTime={latest.started_at}>
              {new Date(latest.started_at).toLocaleString()}
            </time>
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
