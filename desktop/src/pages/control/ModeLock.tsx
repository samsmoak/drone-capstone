/**
 * The Control page of the mode the open session does NOT belong to.
 *
 * A session stays in the mode it started in (lib/sessionMode.ts; the agent
 * refuses a change). So instead of the other mode's controls — which would
 * act on a session checked under different rules — this page says which
 * session is open and offers the way back to it. Land and Emergency stop stay
 * in the flight strip at the top, as on every page.
 */

import type { Mode, Session } from "@/lib/agent";
import { modeName } from "@/lib/sessionMode";
import { Button, Message, PageHeader, Panel } from "@/components/ui";

export function ModeLock({ session, looking, onBack }: {
  session: Session;
  /** The mode whose page the operator chose to look at. */
  looking: Mode;
  onBack: () => void;
}) {
  const open = modeName(session.mode);
  const other = modeName(looking);
  return (
    <div className="grid gap-5">
      <PageHeader eyebrow={other} title="Control" />
      <Panel title={`${other} is closed while a ${open} session is open`} bodyClassName="grid gap-3 px-4 py-4">
        <Message
          tone="warning"
          text={`A session stays in the mode it started in. This one is ${open}, so nothing here can act on it.`}
        />
        <p className="text-sm">
          To fly {other}: go back to {open}, end the session there, then start a new session in {other}.
        </p>
        <div>
          <Button variant="primary" onClick={onBack}>Go to {open}</Button>
        </div>
      </Panel>
    </div>
  );
}
