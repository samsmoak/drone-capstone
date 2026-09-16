"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/ui/states";

/**
 * The error state for every operator page.
 *
 * A failed fetch must say so. Without this boundary a thrown query renders the
 * framework's blank fallback, and an empty panel where a battery voltage
 * belongs reads as "fine" to someone about to fly.
 *
 * The raw message is deliberately not shown: it can carry Postgres column
 * names and policy internals. It goes to the console for whoever is debugging,
 * and the operator gets something they can act on.
 */
export default function OperatorError({
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
          error.digest
            ? `Something went wrong reading from the database. Reference: ${error.digest}`
            : "Something went wrong reading from the database."
        }
        retry={
          <button
            type="button"
            onClick={reset}
            className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
          >
            Try again
          </button>
        }
      />
    </div>
  );
}
