"use client";

import { useState, useTransition } from "react";
import type { MissionRow } from "@/lib/queries";
import { cancelMission } from "@/lib/mutations";
import { StatusBadge } from "@/components/ui/states";
import { LocalTime } from "@/components/ui/local-time";

const TONE: Record<MissionRow["status"], "good" | "warning" | "serious" | "critical"> = {
  queued: "warning",
  claimed: "warning",
  running: "warning",
  done: "good",
  cancelled: "serious",
  failed: "critical",
};

function CancelButton({ mission, canQueue }: { mission: MissionRow; canQueue: boolean }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  if (mission.status !== "queued" || !canQueue) return null;

  return (
    <div className="space-y-1">
      <button
        type="button"
        disabled={pending}
        onClick={() =>
          startTransition(async () => {
            const result = await cancelMission(mission.id);
            setError(result.ok ? null : result.error);
          })
        }
        className="inline-flex min-h-11 items-center rounded-md border border-[var(--border)] px-3 text-sm disabled:opacity-50"
      >
        {pending ? "Cancelling…" : "Cancel"}
        <span className="sr-only"> {mission.name}</span>
      </button>
      {error && (
        <p role="alert" className="max-w-xs text-xs">
          <span aria-hidden="true" style={{ color: "var(--status-critical)" }}>⚠ </span>
          {error}
        </p>
      )}
    </div>
  );
}

export function MissionQueue({ missions, canQueue }: { missions: MissionRow[]; canQueue: boolean }) {
  if (missions.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
        No missions yet. Queued missions appear here and are picked up by the agent in order.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="bg-[var(--surface-2)]">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">Mission</th>
            <th scope="col" className="px-4 py-3 font-medium">Status</th>
            <th scope="col" className="px-4 py-3 font-medium">Created</th>
            <th scope="col" className="px-4 py-3 font-medium">Detail</th>
            <th scope="col" className="px-4 py-3 font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {missions.map((m) => (
            <tr key={m.id} className="border-t border-[var(--border)] align-top">
              <th scope="row" className="px-4 py-3 font-medium">
                {m.name}
                <span className="block text-xs font-normal text-[var(--muted)]">{m.type}</span>
              </th>
              <td className="px-4 py-3">
                <StatusBadge
                  status={TONE[m.status]}
                  label={m.status.charAt(0).toUpperCase() + m.status.slice(1)}
                />
              </td>
              <td className="px-4 py-3">
                <LocalTime iso={m.created_at} />
              </td>
              <td className="px-4 py-3">
                {/* A failed mission's reason is the one thing the operator needs; never hide it. */}
                {m.error ? <span>{m.error}</span> : <span className="text-[var(--muted)]">—</span>}
              </td>
              <td className="px-4 py-3">
                <CancelButton mission={m} canQueue={canQueue} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
