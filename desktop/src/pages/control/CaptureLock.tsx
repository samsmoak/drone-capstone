/**
 * Control while a CAPTURE session is open (2026-10-24).
 *
 * A capture session is the Capture page's: it checked only the radio and the
 * camera's deck, and the agent refuses every flight action in it. So instead
 * of Control's flight controls — which would act on a session never checked
 * for flying — this page says which session is open and the way to fly.
 * Land and Emergency stop stay in the flight strip at the top, as on every page.
 */

// PARITY: desktop/src/pages/control/ModeLock.tsx
// The same lock, for a session's purpose instead of its mode.

import type { Session } from "@/lib/agent";
import { Button, Message, PageHeader, Panel } from "@/components/ui";

export function CaptureLock({ session, onOpenCapture }: {
  session: Session;
  onOpenCapture: () => void;
}) {
  return (
    <div className="grid gap-5">
      <PageHeader eyebrow={session.mode === "auto" ? "Auto" : "Manual"} title="Control" />
      <Panel title="A capture session is open" bodyClassName="grid gap-3 px-4 py-4">
        <Message
          tone="warning"
          text="This session was started on the Capture page to take pictures. It was checked for that only, so nothing here can fly it."
        />
        <p className="text-sm">
          To fly: end the capture session on the Capture page, then start a session here.
        </p>
        <div>
          <Button variant="primary" onClick={onOpenCapture}>Go to Capture</Button>
        </div>
      </Panel>
    </div>
  );
}
