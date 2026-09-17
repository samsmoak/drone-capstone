/** The last few sessions, on the Control page. */

import { useState } from "react";
import type { Mode } from "@/lib/agent";
import { Button, Panel } from "@/components/ui";
import { HiddenByMode, LoadState, MODE_LABEL, SessionRow, useSessions } from "./parts";

export function RecentSessions({ refreshKey, mode, onOpen, onOpenAll }: {
  refreshKey: unknown;
  mode: Mode;
  onOpen: (id: string) => void;
  onOpenAll: () => void;
}) {
  const [allModes, setAllModes] = useState(false);
  const filter = allModes ? null : mode;
  const { state, hidden, reload } = useSessions(5, refreshKey, filter);

  return (
    <Panel
      title={allModes ? "Recent sessions" : `Recent ${MODE_LABEL[mode]} sessions`}
      note="Kept on this computer, online or not."
      action={<Button onClick={onOpenAll}>All sessions →</Button>}
    >
      <div className="grid gap-4">
        <HiddenByMode mode={mode} hidden={hidden} onShowAll={() => setAllModes(true)} />
        <LoadState
          state={state}
          reload={reload}
          empty={state.kind === "ready" && state.data.length === 0}
          emptyText={
            <p>No sessions on this computer yet. Start one from Control — it will be listed here
              with who ran it and when.</p>
          }
        >
          {(records) => (
            <ul className="-mx-4 divide-y divide-[var(--border)]">
              {records.map((r) => <SessionRow key={r.id} record={r} onOpen={() => onOpen(r.id)} />)}
            </ul>
          )}
        </LoadState>
      </div>
    </Panel>
  );
}
