import Link from "next/link";
import { getLatestZoneHealth, getZones } from "@/lib/queries";
import { EmptyState } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { ZoneLegend, ZoneMap } from "@/components/ui/zone-map";
import { FLIGHTS } from "@/lib/routes";
import { LocalTime } from "@/components/ui/local-time";

export const metadata = { title: "Zones" };

export default async function ZonesPage() {
  const [zones, health] = await Promise.all([getZones(), getLatestZoneHealth()]);

  if (zones.length === 0) {
    return (
      <div className="space-y-8">
        <PageHeader title="Zones" />
        <EmptyState
          title="No zones defined"
          hint="Zones divide the greenhouse floor into areas the drone reports on. They are added to the zones table in Supabase."
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Zones"
        description="The greenhouse from above. Each zone shows its most recent health estimate, from whichever flight last covered it."
      />

      {health.size === 0 && (
        <p
          role="status"
          className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm"
        >
          No health estimates yet. The map fills in once the agent runs crop-health
          inference after a flight. Flight telemetry is already available under{" "}
          <Link href={FLIGHTS} className="underline underline-offset-4">
            Flights
          </Link>
          .
        </p>
      )}

      <section aria-labelledby="map-heading" className="space-y-4">
        <h2 id="map-heading" className="sr-only">
          Zone map
        </h2>
        {/* Scrolls inside its box on a phone rather than shrinking the labels to ~6 px. */}
        <div
          tabIndex={0}
          role="region"
          aria-label="Zone map"
          className="max-w-3xl overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
        >
          <ZoneMap zones={zones} health={health} />
        </div>
        <ZoneLegend />
      </section>

      {/* The table view: every figure on the map, readable without colour. */}
      <section aria-labelledby="table-heading" className="space-y-3">
        <h2 id="table-heading" className="text-lg font-semibold">
          All zones
        </h2>
        <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[var(--surface-2)]">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Zone</th>
                <th scope="col" className="px-4 py-3 font-medium">Health score</th>
                <th scope="col" className="px-4 py-3 font-medium">Disease risk</th>
                <th scope="col" className="px-4 py-3 font-medium">Label</th>
                <th scope="col" className="px-4 py-3 font-medium">Bounds (m)</th>
                <th scope="col" className="px-4 py-3 font-medium">Estimated</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => {
                const p = health.get(z.id);
                return (
                  <tr key={z.id} className="border-t border-[var(--border)]">
                    <th scope="row" className="px-4 py-3 font-medium">{z.label}</th>
                    <td className="tabular px-4 py-3">{p?.health_score?.toFixed(2) ?? "—"}</td>
                    <td className="tabular px-4 py-3">{p?.disease_risk?.toFixed(2) ?? "—"}</td>
                    <td className="px-4 py-3">{p?.label ?? "—"}</td>
                    <td className="tabular px-4 py-3">
                      x {z.x_min} to {z.x_max}, y {z.y_min} to {z.y_max}
                    </td>
                    <td className="px-4 py-3">
                      {p ? (
                        <Link
                          href={`${FLIGHTS}/${p.flight_id}`}
                          className="inline-flex min-h-11 items-center underline underline-offset-4"
                        >
                          <LocalTime iso={p.created_at} />
                        </Link>
                      ) : (
                        "Never"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
