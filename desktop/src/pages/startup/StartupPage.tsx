/**
 * What the window shows before it knows anything.
 *
 * Two things are unknown when the app opens: whether the flight agent is up
 * (it starts alongside the window) and whether the saved sign-in still works
 * (a network call). Rendering the signed-out page in that gap told the operator
 * "not signed in", then swapped it for their account a second later. This holds
 * the page's shape and says what it is waiting for.
 */

import { useEffect, useState } from "react";
import { Message, Skeleton, SkeletonPanel, Spinner } from "@/components/ui";

/** How long to wait before saying that this is taking longer than it should. */
const PATIENCE_MS = 12000;

export function StartupPage({ connected }: { connected: boolean }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), PATIENCE_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="grid gap-5">
      {/* The shape of the page that is coming: an eyebrow, a title, a line of
          description. The sidebar and the strip are already real by now — only
          the page itself is unknown. */}
      <header className="grid gap-1.5">
        <Skeleton className="h-2.5 w-20" />
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-4 w-full max-w-xl" />
      </header>

      <p className="sr-only" role="status" aria-live="polite">
        {connected ? "Signing you back in" : "Starting the flight agent"}
      </p>
      <Spinner label={connected ? "Signing you back in…" : "Starting the flight agent on this computer…"} />

      {slow && (
        <Message
          tone="warning"
          text={
            connected
              ? "Signing back in is taking longer than usual. Check this computer's internet connection — you can still sign in by hand once this clears."
              : "The flight agent has not answered. It may not have started, or another copy of CropWatcher may already be running. Quit any other copy and reopen this window."
          }
        />
      )}

      {/* Five across, matching Home's status row, so nothing jumps when the
          real figures arrive. */}
      <section aria-hidden="true" className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="min-w-0 border border-[var(--border)] bg-[var(--surface)] p-4">
            <Skeleton className="h-2.5 w-16" />
            <Skeleton className="mt-2.5 h-6 w-20" />
            <Skeleton className="mt-2.5 h-2.5 w-24" />
          </div>
        ))}
      </section>

      <div aria-hidden="true" className="grid gap-4">
        <SkeletonPanel lines={4} />
        <SkeletonPanel lines={2} />
      </div>
    </div>
  );
}
