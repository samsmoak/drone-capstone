"use client";

import { useEffect, useState } from "react";

type Status = "checking" | "running" | "absent";

const AGENT_URL = process.env.NEXT_PUBLIC_AGENT_URL ?? "http://127.0.0.1:8765";

/**
 * Whether the CropWatcher app is installed and running on this machine.
 *
 * The page tells you where you are instead of making you guess. All three
 * states say something useful — "absent" is a normal outcome for a visitor
 * reading the guide, not an error.
 */
export function AgentStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let cancelled = false;
    // Short timeout: an unreachable localhost port should resolve fast, not
    // leave the banner spinning while the browser waits to give up.
    const timeout = AbortSignal.timeout(2000);

    fetch(`${AGENT_URL}/health`, { signal: timeout })
      .then((r) => (r.ok ? "running" : "absent"))
      .catch(() => "absent")
      .then((next) => {
        if (!cancelled) setStatus(next as Status);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "checking") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--muted)]"
      >
        Checking whether CropWatcher is running on this computer…
      </div>
    );
  }

  const running = status === "running";

  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-lg border bg-[var(--surface)] px-4 py-3 text-sm"
      style={{
        borderColor: running ? "var(--status-good)" : "var(--border)",
      }}
    >
      <p className="flex items-center gap-2 font-medium">
        {/* Icon + words. The colour is a second signal, never the only one. */}
        <span
          aria-hidden="true"
          style={{ color: running ? "var(--status-good)" : "var(--muted)" }}
        >
          {running ? "●" : "○"}
        </span>
        {running
          ? "CropWatcher is running on this computer"
          : "CropWatcher is not running on this computer"}
      </p>
      <p className="mt-1 text-[var(--muted)]">
        {running
          ? "You can skip to step 3."
          : "That is expected if you are just reading. Start at step 1 to set it up."}
      </p>
    </div>
  );
}
