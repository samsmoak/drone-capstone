import { getMissions, getZones, isOperator } from "@/lib/queries";
import { EmptyState } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { MissionPlanner } from "@/components/mission-planner";
import { MissionQueue } from "@/components/mission-queue";

export const metadata = { title: "Plan a mission" };

export default async function PlanPage() {
  const [zones, missions, operator] = await Promise.all([getZones(), getMissions(20), isOperator()]);

  return (
    <div className="space-y-10">
      <PageHeader
        title="Plan a mission"
        description="Choose zones in the order the drone should visit them. The mission is queued in Supabase and flown by the agent on the computer with the radio."
      />

      {zones.length === 0 ? (
        <EmptyState
          title="No zones to plan over"
          hint="Missions are built from zones. Add zones to the zones table first."
        />
      ) : (
        // The operator check here only shapes the UI. Queuing is enforced by
        // RLS in Postgres, whatever this page shows.
        <MissionPlanner zones={zones} canQueue={operator} />
      )}

      <section aria-labelledby="queue-heading" className="space-y-3">
        <h2 id="queue-heading" className="text-lg font-semibold">
          Recent missions
        </h2>
        <MissionQueue missions={missions} canQueue={operator} />
      </section>
    </div>
  );
}
