/**
 * Anything, at the size of the whole window.
 *
 * The command log had this first, and the console's tabs wanted the same thing
 * — a chart or a camera frame in a third of a split column is a thumbnail. Two
 * uses of one interaction, so it is one component rather than two overlays with
 * the same keyboard handling copied between them.
 *
 * Modal conventions, because it is one: Escape closes, focus moves in on open
 * and back to whatever opened it on close, and THE BACKDROP IS INERT TO CLICKS.
 * A stray click dismissing what an operator is reading mid-flight is worse than
 * making them find Escape or the button.
 */

import { useEffect, useRef, type ReactNode } from "react";

export function FullScreenOverlay({ label, onClose, action, children }: {
  /** Names the dialog for a screen reader, and titles the bar. */
  label: string;
  onClose: () => void;
  /** Anything extra in the bar, left of Close. */
  action?: ReactNode;
  children: ReactNode;
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    closeButton.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Put focus back where it was. Leaving it on a removed node drops the
      // keyboard to the top of the page.
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={label}
      className="fixed inset-0 z-50 flex flex-col bg-[var(--console)]"
    >
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--console-line)] px-4 py-2">
        <h2 className="mono min-w-0 truncate text-xs font-bold uppercase tracking-[0.1em] text-[var(--console-ink)]">
          {label}
        </h2>
        <div className="flex shrink-0 items-center gap-2">
          {action}
          <button
            ref={closeButton}
            type="button"
            onClick={onClose}
            className="mono min-h-8 border border-[var(--console-line)] px-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--console-ink)]"
          >
            Close (Esc)
          </button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
