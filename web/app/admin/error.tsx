"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ErrorState } from "@/components/ui/states";
import { ADMIN } from "@/lib/routes";

/**
 * The error state for every admin page.
 *
 * PARITY: app/app/error.tsx — same boundary, adapted for the editors.
 *
 * Admin reads throw on failure by design (lib/queries.ts), and every editor
 * calls router.refresh() after a save, which re-runs them. Without this file a
 * throw at that moment rendered Next's bare fallback — "This page couldn't
 * load", a Reload button, and an error code — which is what an operator saw
 * when a save coincided with an expired session (2026-09-21). Worse, the
 * editor unmounted and everything typed since the last save went with it.
 *
 * Try again re-runs the failed render without a full page load, so a draft
 * held in the editor survives. What could not be recovered is offered from the
 * local draft instead (lib/use-draft.ts).
 *
 * The raw message stays out of the UI: it can carry Postgres column names and
 * policy internals. It goes to the console, and the operator gets the
 * reference code that appears in the server log beside it.
 */
export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="py-8">
      <ErrorState
        title="Could not load this page"
        detail={
          "Something went wrong reading from the database — often a sign-in that has " +
          "expired while the page was open. Try again; if it keeps happening, open the " +
          "admin in a new tab and sign in again." +
          (error.digest ? ` Reference: ${error.digest}` : "")
        }
        retry={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={reset}
              className="inline-flex min-h-11 cursor-pointer items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
            >
              Try again
            </button>
            <Link
              href={ADMIN}
              className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 font-medium"
            >
              Back to the admin
            </Link>
          </div>
        }
      />
      <p className="mt-4 max-w-prose text-sm text-[var(--muted)]">
        Anything you had typed is kept in this browser. Reopen the page you were editing and
        it will offer to put it back.
      </p>
    </div>
  );
}
