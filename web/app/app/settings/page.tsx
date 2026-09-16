import { getDrones } from "@/lib/queries";
import { PageHeader } from "@/components/ui/page-header";
import { AgentReachability } from "@/components/agent-reachability";
import { metresToFeet } from "@/lib/flight-format";
import {
  ALTITUDE_MAX_M,
  ALTITUDE_MIN_M,
  FENCE_HALF_EXTENT_M,
} from "@/lib/mission-plan";

export const metadata = { title: "Settings" };

/**
 * What the system is actually configured to do.
 *
 * Deliberately read-only. The geofence the drone obeys is the agent's
 * `--fence` flag, and the drone URI is the agent's — a value edited and stored
 * in a browser would change nothing about how the drone flies, while looking
 * as if it had. Each setting says where it really lives and how to change it.
 */
export default async function SettingsPage() {
  const drones = await getDrones();
  const side = FENCE_HALF_EXTENT_M * 2;

  return (
    <div className="space-y-10">
      <PageHeader
        title="Settings"
        description="What the system is configured to do, and where each value really lives."
      />

      <section aria-labelledby="agent-heading" className="space-y-3">
        <h2 id="agent-heading" className="text-lg font-semibold">
          Agent
        </h2>
        <AgentReachability />
      </section>

      <section aria-labelledby="fence-heading" className="space-y-3">
        <h2 id="fence-heading" className="text-lg font-semibold">
          Geofence
        </h2>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5">
          <dl className="grid gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs uppercase tracking-wide text-[var(--muted)]">Flight area</dt>
              <dd className="tabular mt-1 text-lg font-semibold">
                {side.toFixed(1)} × {side.toFixed(1)} m
              </dd>
              <dd className="text-xs text-[var(--muted)]">
                x and y within ±{FENCE_HALF_EXTENT_M.toFixed(1)} m of Lighthouse origin ·{" "}
                {metresToFeet(side).toFixed(1)} ft square
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-[var(--muted)]">Lowest altitude</dt>
              <dd className="tabular mt-1 text-lg font-semibold">{ALTITUDE_MIN_M.toFixed(2)} m</dd>
              <dd className="text-xs text-[var(--muted)]">above the floor at takeoff</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-[var(--muted)]">Highest altitude</dt>
              <dd className="tabular mt-1 text-lg font-semibold">{ALTITUDE_MAX_M.toFixed(2)} m</dd>
              <dd className="text-xs text-[var(--muted)]">above the floor at takeoff</dd>
            </div>
          </dl>
          <p className="mt-4 text-sm text-[var(--muted)]">
            The agent enforces these before it arms; the planner checks the same numbers so a
            problem shows up while planning. To fly a larger area, start the agent with{" "}
            <code className="rounded bg-[var(--surface-2)] px-1.5 py-0.5 text-[var(--foreground)]">
              cropwatcher poll --fence 2.5
            </code>{" "}
            — the planner here still checks against ±{FENCE_HALF_EXTENT_M.toFixed(1)} m until it is
            updated to match.
          </p>
        </div>
      </section>

      <section aria-labelledby="drones-heading" className="space-y-3">
        <h2 id="drones-heading" className="text-lg font-semibold">
          Drones
        </h2>
        {drones.length === 0 ? (
          <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5 text-sm text-[var(--muted)]">
            No drones registered. The agent uses its default radio address,{" "}
            <code className="tabular text-[var(--foreground)]">radio://0/80/2M</code>,
            unless started with <code className="text-[var(--foreground)]">--uri</code>.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-[var(--surface-2)]">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Name</th>
                  <th scope="col" className="px-4 py-3 font-medium">Radio URI</th>
                  <th scope="col" className="px-4 py-3 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {drones.map((d) => (
                  <tr key={d.id} className="border-t border-[var(--border)]">
                    <th scope="row" className="px-4 py-3 font-medium">{d.name}</th>
                    <td className="tabular px-4 py-3">{d.uri}</td>
                    <td className="px-4 py-3">{d.notes ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
