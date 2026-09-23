/**
 * What the window asked for, and what the agent said back.
 *
 * Newest at the bottom, like a terminal. It follows the tail on its own, but
 * **autoscroll stops the moment the operator scrolls up** — a log that yanks
 * itself back to the bottom while you are reading the line that failed is a log
 * you cannot use. A button comes back when it has been left behind.
 *
 * It says on screen what it is not: this starts when the window opens and dies
 * with it. The flight record, and the agent's audit trail, are elsewhere.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { KIND_COLOR, KIND_GLYPH, type LogLine } from "@/lib/commandLog";
import { formatClock } from "@/lib/format";

/** Within this many pixels of the bottom still counts as "at the bottom". */
const STICK_PX = 24;

export function CommandLog({ lines, onClear }: { lines: LogLine[]; onClear: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  // Before paint, so the view never shows the pre-scroll position first.
  useLayoutEffect(() => {
    if (!pinned) return;
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, pinned]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_PX;
      setPinned(atBottom);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={box}
        // A log region, announced only when the operator has asked for it by
        // reading it — polite, never assertive: the alerts are the Messages.
        role="log"
        aria-label="Command log"
        aria-live="polite"
        className="console console-scroll min-h-0 flex-1 overflow-y-auto px-3 py-2"
      >
        {lines.length === 0 ? (
          <p className="text-[var(--console-dim)]">
            Nothing yet. Commands and the agent's replies appear here as they happen.
          </p>
        ) : (
          <ol>
            {lines.map((line) => (
              <li key={line.id} className="flex gap-2">
                <span className="shrink-0 text-[var(--console-dim)]">{formatClock(line.at)}</span>
                {/* Glyph AND colour, never colour alone. */}
                <span aria-hidden="true" className="w-3 shrink-0" style={{ color: KIND_COLOR[line.kind] }}>
                  {KIND_GLYPH[line.kind]}
                </span>
                <span className="min-w-0 break-words">
                  <span style={{ color: KIND_COLOR[line.kind] }}>{line.text}</span>
                  {line.detail && (
                    <span className="text-[var(--console-dim)]"> — {line.detail}</span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {!pinned && lines.length > 0 && (
        <button
          type="button"
          onClick={() => {
            setPinned(true);
            const el = box.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
          className="absolute bottom-9 right-4 min-h-8 border border-[var(--border)] bg-[var(--surface)] px-3 text-xs font-semibold shadow-lg"
        >
          Jump to newest ↓
        </button>
      )}

      <div className="flex items-center justify-between gap-3 border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5">
        <p className="mono text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">
          {lines.length} line{lines.length === 1 ? "" : "s"} · this window only, not the flight record
        </p>
        <button
          type="button"
          onClick={onClear}
          disabled={lines.length === 0}
          className="mono min-h-7 px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--console-dim)] hover:text-[var(--console-ink)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Clear
        </button>
      </div>
    </div>
  );
}
