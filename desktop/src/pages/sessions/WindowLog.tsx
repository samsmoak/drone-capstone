/** One sensor window's readings, grouped by session. */

import { useState } from "react";
import type { Mode } from "@/lib/agent";
import { formatDateTime, formatDuration } from "@/lib/format";
import { PageHeader } from "@/components/ui";
import { WINDOWS, WINDOW_VARIABLES, type WindowKey } from "@/pages/windows/SensorWindow";
import {
  DashboardLink, Disclosure, HiddenByMode, LoadState, MODE_LABEL, READINGS_SHOWN, ReadingsTable,
  Who, useSessions,
} from "./parts";

/** Sessions listed before the dashboard takes over. */
const SESSIONS_SHOWN = 10;

/** Opened on arrival, so the log shows readings without another click. */
const OPEN_ON_ARRIVAL = 3;

export function WindowLog({ windowKey, refreshKey, mode, onBack }: {
  windowKey: WindowKey;
  refreshKey: unknown;
  mode: Mode;
  onBack: () => void;
}) {
  const page = WINDOWS.find((w) => w.key === windowKey)!;
  const [allModes, setAllModes] = useState(false);
  const filter = allModes ? null : mode;
  const { state, hidden, reload } = useSessions(SESSIONS_SHOWN, refreshKey, filter);

  return (
    <div className="grid gap-6">
      <div>
        <button type="button" onClick={onBack}
                className="text-sm font-semibold text-[var(--muted)] hover:text-[var(--foreground)]">
          ← Live {page.label.toLowerCase()}
        </button>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeader title={`${page.label} log${allModes ? "" : ` · ${MODE_LABEL[mode]}`}`}>
          Past sessions on this computer — the latest {SESSIONS_SHOWN}, with their most recent
          {" "}{READINGS_SHOWN} {page.label.toLowerCase()} readings each. The live page shows what
          the drone is doing right now.
        </PageHeader>
        <DashboardLink>View all in the dashboard</DashboardLink>
      </div>

      <HiddenByMode mode={mode} hidden={hidden} onShowAll={() => setAllModes(true)} />

      <LoadState
        state={state}
        reload={reload}
        empty={state.kind === "ready" && state.data.length === 0}
        emptyText={<p>No sessions recorded on this computer yet.</p>}
      >
        {(records) => (
          <div className="grid gap-3">
            {records.map((r, i) => (
              <Disclosure
                key={r.id}
                open={i < OPEN_ON_ARRIVAL}
                summaryClassName="grid cursor-pointer list-none gap-1 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center"
                summary={
                  <>
                    <span>
                      <span className="block font-semibold">{formatDateTime(r.started_at)}</span>
                      <span className="block text-sm text-[var(--muted)]">
                        <Who record={r} /> · {MODE_LABEL[r.mode as Mode] ?? r.mode} ·{" "}
                        {r.ended_at ? formatDuration(r.duration_s) : "running"} · {r.summary.samples} readings
                      </span>
                    </span>
                    <span className="text-sm text-[var(--muted)]">
                      <span className="group-open:hidden">Show readings ›</span>
                      <span className="hidden group-open:inline">Hide readings</span>
                    </span>
                  </>
                }
              >
                {() => (
                  <ReadingsTable sessionId={r.id} variables={WINDOW_VARIABLES[windowKey]} mode={filter} />
                )}
              </Disclosure>
            ))}
          </div>
        )}
      </LoadState>
    </div>
  );
}
