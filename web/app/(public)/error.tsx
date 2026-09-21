"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ErrorState } from "@/components/ui/states";
import { HOME } from "@/lib/routes";

/**
 * The error state for the visitor site.
 *
 * PARITY: app/app/error.tsx — same boundary, wording for a visitor rather than
 * an operator: nothing here is theirs to fix, so it offers a retry and a way
 * home instead of an explanation of the database.
 */
export default function SiteError({
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
    <main className="mx-auto w-full max-w-2xl px-6 py-20">
      <ErrorState
        title="This page could not be loaded"
        detail={
          "Something went wrong at our end, not yours." +
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
              href={HOME}
              className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 font-medium"
            >
              Go to the home page
            </Link>
          </div>
        }
      />
    </main>
  );
}
