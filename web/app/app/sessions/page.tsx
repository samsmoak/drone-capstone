import Link from "next/link";
import { getRecentSessions } from "@/lib/queries";
import { EmptyState, StatusBadge } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { SESSIONS } from "@/lib/routes";
import { flightDuration } from "@/lib/flight-format";
import { LocalTime } from "@/components/ui/local-time";
import { Owner } from "@/components/ui/owner";

export const metadata = { title: "Sessions" };

/**
 * Every session, newest first — Start session to End session, flying or not.
 * A flight is part of a session; this is the whole of it (2026-10-06, Samuel:
 * "everything in it, not just flights"). The page per session reads like the
 * flight page, over the session's own one-a-second vitals.
 */
export default async function SessionsPage() {
  const sessions = await getRecentSessions(50);

  if (sessions.length === 0) {
    return (
      <div className="space-y-8">
        <PageHeader title="Sessions" description="Every session the agent has recorded." />
        <EmptyState
          title="No sessions recorded yet"
          hint="A session appears here once the desktop app starts one and the agent uploads it."
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Sessions"
        description="Every session the agent has recorded, newest first — with or without a flight."
      />

      <div className="overflow-x-auto [contain:paint] rounded-lg border border-[var(--border)]">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Recorded sessions, newest first</caption>
          <thead className="bg-[var(--surface-2)]">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Started</th>
              <th scope="col" className="px-4 py-3 font-medium">Status</th>
              <th scope="col" className="px-4 py-3 font-medium">Duration</th>
              <th scope="col" className="px-4 py-3 font-medium">Mode</th>
              <th scope="col" className="px-4 py-3 font-medium">Run by</th>
              <th scope="col" className="px-4 py-3 font-medium">Drone</th>
              <th scope="col" className="px-4 py-3 font-medium">Flights</th>
              <th scope="col" className="px-4 py-3 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="border-t border-[var(--border)]">
                <th scope="row" className="px-4 py-3 font-normal">
                  <LocalTime iso={s.started_at} />
                </th>
                <td className="px-4 py-3">
                  <StatusBadge status={s.ended_at ? "good" : "warning"}
                               label={s.ended_at ? "Ended" : "Open"} />
                </td>
                <td className="tabular px-4 py-3">{flightDuration(s.started_at, s.ended_at)}</td>
                <td className="px-4 py-3">{s.mode_at_start ?? "—"}</td>
                <td className="px-4 py-3"><Owner who={s} /></td>
                <td className="px-4 py-3">{s.drone ?? "—"}</td>
                <td className="tabular px-4 py-3">{s.flight_count}</td>
                <td className="px-4 py-3 text-right">
                  <Link href={`${SESSIONS}/${s.id}`}
                        className="inline-flex min-h-11 items-center underline underline-offset-4">
                    Open<span className="sr-only">{" "}session from <LocalTime iso={s.started_at} /></span>
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
