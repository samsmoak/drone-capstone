/**
 * An OS notification when a flight finishes processing with a finding of
 * warning or worse — so an operator who is not looking at the Control page
 * still hears about it. The web app keeps the same findings as persistent
 * notifications (web/components/operator/notifications.tsx); this one is the
 * laptop's own, and only for a job that finished while the app was open.
 *
 * Fails quietly: in the layout harness there is no OS to ask, and an operator
 * may have refused permission. The Data processing panel shows the findings
 * either way.
 */

import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import type { PipelineFinding } from "@/lib/agent";

/** Flights already announced this run: one notification per flight. */
const announced = new Set<string>();

export async function announceFindings(flightId: string, findings: PipelineFinding[]): Promise<void> {
  const serious = findings.filter((f) => f.severity === "warning" || f.severity === "critical");
  if (serious.length === 0 || announced.has(flightId)) return;
  announced.add(flightId);
  try {
    let granted = await isPermissionGranted();
    if (!granted) granted = (await requestPermission()) === "granted";
    if (!granted) return;
    const worst = serious.find((f) => f.severity === "critical") ?? serious[0];
    sendNotification({
      title: serious.length === 1 ? "A finding in the last flight" : `${serious.length} findings in the last flight`,
      body: `${worst.severity === "critical" ? "Critical" : "Warning"}: ${worst.title}`,
    });
  } catch {
    // Not in the app, or the OS said no: the panel shows the findings anyway.
  }
}
