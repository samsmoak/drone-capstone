/**
 * Two panes with a divider you can drag, and that stays where it is left.
 *
 * Used twice on Control: the console against the controls (a vertical divider
 * you drag sideways), and inside the console the attitude indicator against the
 * command log (a horizontal one you drag up and down). One component, because
 * the second was going to be a copy of the first with the axis swapped.
 *
 * IT IS A REAL SEPARATOR, not a draggable div. WAI-ARIA's window splitter
 * pattern: role="separator", an orientation, a value with bounds, in the tab
 * order, and arrow keys that move it. A divider only a mouse can reach is one
 * an operator on a laptop trackpad, mid-flight, cannot use.
 *
 * THE FRACTION IS CLAMPED, always. Dragging to an edge would otherwise leave a
 * pane at zero with no way to get it back — the divider would be flush against
 * the frame and there would be nothing to grab.
 *
 * Double-click resets to the default. That is the standard escape hatch for a
 * splitter dragged somewhere unhelpful, and it costs one handler.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/** How much of the container the FIRST pane may take, at the extremes.
 *
 * Per instance, because the two splitters want different room. The console's
 * inner divider has to fold the attitude indicator almost away — that is the
 * whole point of dragging it up to read the log — while the outer one should
 * never let either column become a sliver. A single 20 % floor made the inner
 * one feel broken: it stopped a fifth of the way down with nothing to explain
 * why.
 *
 * NEVER 0. A pane dragged to nothing takes the divider to the frame edge with
 * it, and there is no handle left to bring it back. */
const DEFAULT_MIN = 0.2;
const DEFAULT_MAX = 0.8;

/** Arrow keys move by this much; with Shift, five times as much. */
const KEY_STEP = 0.02;

function load(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const value = Number(raw);
    // A stored value from an older build, or a hand-edited one, must not be
    // able to collapse a pane.
    return Number.isFinite(value) ? clampTo(value, min, max) : fallback;
  } catch {
    return fallback;
  }
}

const clampTo = (f: number, min: number, max: number) => Math.min(max, Math.max(min, f));

export function SplitPane({
  orientation, storageKey, defaultFraction, first, second, label, className = "",
  min = DEFAULT_MIN, max = DEFAULT_MAX,
}: {
  /** "vertical" = panes side by side, divider runs up and down.
   *  "horizontal" = panes stacked, divider runs across. Matches
   *  aria-orientation, which describes the SEPARATOR, not the layout. */
  orientation: "vertical" | "horizontal";
  storageKey: string;
  /** Share of the container the first pane gets before anyone drags. */
  defaultFraction: number;
  first: ReactNode;
  second: ReactNode;
  /** Names the divider for a screen reader — "Console and controls". */
  label: string;
  className?: string;
  /** How small the first pane may get. Below DEFAULT_MIN for a pane that is
   *  meant to fold away, never 0 — see the note on the constants. */
  min?: number;
  max?: number;
}) {
  const [fraction, setFraction] = useState(() => load(storageKey, defaultFraction, min, max));
  const [dragging, setDragging] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { localStorage.setItem(storageKey, String(fraction)); } catch { /* private window */ }
  }, [storageKey, fraction]);

  const sideBySide = orientation === "vertical";

  const fromPointer = useCallback((event: PointerEvent | React.PointerEvent) => {
    const el = box.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const next = sideBySide
      ? (event.clientX - rect.left) / rect.width
      : (event.clientY - rect.top) / rect.height;
    setFraction(clampTo(next, min, max));
  }, [sideBySide, min, max]);

  // Listeners go on the WINDOW, not the divider: a pointer moving faster than
  // React re-renders leaves the element behind, and the drag would stick.
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => { e.preventDefault(); fromPointer(e); };
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    // While dragging, the cursor is the divider's wherever it happens to be,
    // and text must not select under it.
    const previous = document.body.style.cursor;
    document.body.style.cursor = sideBySide ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      document.body.style.cursor = previous;
      document.body.style.userSelect = "";
    };
  }, [dragging, fromPointer, sideBySide]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? KEY_STEP * 5 : KEY_STEP;
    const back = sideBySide ? "ArrowLeft" : "ArrowUp";
    const forward = sideBySide ? "ArrowRight" : "ArrowDown";
    if (event.key === back) { event.preventDefault(); setFraction((f) => clampTo(f - step, min, max)); }
    else if (event.key === forward) { event.preventDefault(); setFraction((f) => clampTo(f + step, min, max)); }
    else if (event.key === "Home") { event.preventDefault(); setFraction(min); }
    else if (event.key === "End") { event.preventDefault(); setFraction(max); }
    else if (event.key === "Enter") { event.preventDefault(); setFraction(clampTo(defaultFraction, min, max)); }
  };

  return (
    <div
      ref={box}
      className={`flex min-h-0 min-w-0 ${sideBySide ? "flex-row" : "flex-col"} ${className}`}
    >
      <div className="flex min-h-0 min-w-0" style={{ flex: `0 0 ${fraction * 100}%` }}>
        {first}
      </div>

      <div
        role="separator"
        aria-orientation={orientation}
        aria-label={label}
        aria-valuenow={Math.round(fraction * 100)}
        aria-valuemin={Math.round(min * 100)}
        aria-valuemax={Math.round(max * 100)}
        tabIndex={0}
        onPointerDown={(e) => { e.preventDefault(); setDragging(true); fromPointer(e); }}
        onDoubleClick={() => setFraction(clampTo(defaultFraction, min, max))}
        onKeyDown={onKeyDown}
        title="Drag to resize · double-click to reset · arrow keys work"
        // The hit area is wider than the line: a 1px target is a WCAG failure
        // and a usability one. The line itself stays hairline.
        className={`group relative shrink-0 ${
          sideBySide ? "w-2 cursor-col-resize" : "h-2 cursor-row-resize"
        }`}
      >
        <span
          aria-hidden="true"
          className={`absolute bg-[var(--border)] transition-colors group-hover:bg-[var(--primary)] ${
            dragging ? "bg-[var(--primary)]" : ""
          } ${
            sideBySide
              ? "inset-y-0 left-1/2 w-px -translate-x-1/2 group-hover:w-0.5"
              : "inset-x-0 top-1/2 h-px -translate-y-1/2 group-hover:h-0.5"
          }`}
        />
        {/* A grip, so the divider reads as draggable before it is touched. */}
        <span
          aria-hidden="true"
          className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-[var(--border)] group-hover:bg-[var(--primary)] ${
            sideBySide ? "h-8 w-[3px]" : "h-[3px] w-8"
          }`}
        />
      </div>

      <div className="flex min-h-0 min-w-0 flex-1">{second}</div>
    </div>
  );
}
