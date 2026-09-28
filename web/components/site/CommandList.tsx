"use client";

import { useState } from "react";

/*
 * Copied from ../doctor-portfolio/components/public/ContactLinks.tsx — the
 * copyable contact rows: a whole-row button, navigator.clipboard, "Copy" turning
 * to "Copied" with a check for 1.5 s, and a silent no-op where the clipboard is
 * unavailable. Adapted only where this page forces it:
 *
 *   contact value, truncated        a command, WRAPPED — a command cut off with
 *                                   an ellipsis cannot be read or checked
 *   icon tile                       the step's number, so the order is visible
 *   portfolio tokens                this site's tokens, and a monospace face
 */

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-3.5 w-3.5" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V6a2 2 0 0 1 2-2h9" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} className="h-3.5 w-3.5" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  );
}

/**
 * Terminal commands, one per row, each copied by clicking it.
 *
 * `numbered` (the default) is for steps run in order. A reference list turns
 * it off, and passes `notes` — one line per command, saying what it does,
 * shown under its row rather than inside the button so it is not copied.
 */
export function CommandList({
  commands,
  notes = [],
  numbered = true,
}: {
  commands: string[];
  notes?: string[];
  numbered?: boolean;
}) {
  const [copied, setCopied] = useState<number | null>(null);

  async function copy(index: number, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(index);
      window.setTimeout(() => setCopied((c) => (c === index ? null : c)), 1500);
    } catch {
      /* clipboard unavailable — no-op */
    }
  }

  if (commands.length === 0) return null;

  const List = numbered ? "ol" : "ul";
  return (
    <List className={numbered ? "grid gap-2" : "grid gap-3"}>
      {commands.map((command, i) => {
        const done = copied === i;
        const note = notes[i];
        return (
          <li key={`${i}-${command}`}>
            <button
              type="button"
              onClick={() => copy(i, command)}
              title="Click to copy"
              aria-label={numbered ? `Copy command ${i + 1}: ${command}` : `Copy command: ${command}`}
              className={`group flex w-full min-w-0 cursor-pointer items-start gap-3 rounded-lg border bg-[var(--surface-2)] px-3.5 py-2.5 text-left transition-colors ${
                done ? "border-[var(--heading)]" : "border-[var(--border)] hover:border-[var(--heading)]"
              }`}
            >
              {numbered && (
                <span
                  aria-hidden="true"
                  className="tabular mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded text-[11px] font-semibold text-[var(--muted)] ring-1 ring-[var(--border)]"
                >
                  {i + 1}
                </span>
              )}
              <code className="min-w-0 flex-1 font-mono text-[13px] leading-5 wrap-anywhere">
                <span aria-hidden="true" className="select-none text-[var(--muted)]">$ </span>
                {command}
              </code>
              <span
                aria-live="polite"
                className={`mt-px inline-flex shrink-0 items-center gap-1 text-xs font-semibold ${
                  done ? "text-[var(--heading)]" : "text-[var(--muted)] group-hover:text-[var(--foreground)]"
                }`}
              >
                {done ? <><CheckIcon /> Copied</> : <><CopyIcon /> Copy</>}
              </span>
            </button>
            {note && <p className="mt-1.5 px-1 text-sm text-[var(--muted)]">{note}</p>}
          </li>
        );
      })}
    </List>
  );
}
