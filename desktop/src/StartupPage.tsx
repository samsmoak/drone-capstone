/**
 * What the window shows before it knows anything.
 *
 * Two things are unknown when the app opens: whether the flight agent is up
 * (it starts alongside the window) and whether the saved sign-in still works
 * (a network call). Rendering the signed-out page in that gap told the operator
 * "not signed in", then swapped it for their account a second later. This holds
 * the page's shape and says what it is waiting for.
 */

import { Skeleton, SkeletonPanel, Spinner } from "./ui";

export function StartupPage({ connected }: { connected: boolean }) {
  return (
    <div className="grid gap-6">
      <header className="grid gap-2">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-4 w-full max-w-xl" />
      </header>

      <p className="sr-only" role="status" aria-live="polite">
        {connected ? "Signing you back in" : "Starting the flight agent"}
      </p>
      <Spinner label={connected ? "Signing you back in…" : "Starting the flight agent on this computer…"} />

      <section aria-hidden="true" className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-24" />
            <Skeleton className="mt-3 h-3 w-28" />
          </div>
        ))}
      </section>

      <div aria-hidden="true" className="grid gap-5">
        <SkeletonPanel lines={4} />
        <SkeletonPanel lines={2} />
      </div>
    </div>
  );
}
