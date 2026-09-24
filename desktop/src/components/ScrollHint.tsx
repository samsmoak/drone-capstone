/**
 * A scrolling area that says when there is more below — and only then.
 *
 * The controls column runs past the bottom of the window often enough that
 * people miss the Checks panel under it, but a permanent "scroll" label is
 * noise the moment you know. This watches the actual scroll extent and shows
 * the hint only while it is TRUE: it appears when content overflows, and goes
 * as soon as the end is reached.
 *
 * The fade is the real affordance and the words are the fallback — a gradient
 * alone is invisible to a screen reader and to anyone who has turned contrast
 * up, so the count of what is hidden is said in text too.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/** Treat this close to the bottom as "at the bottom" — a fractional scroll
 *  position otherwise leaves the hint on for ever at the end of a list. */
const END_PX = 8;

export function ScrollHint({ children, className = "" }: {
  children: ReactNode;
  className?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);

  const measure = useCallback(() => {
    const el = box.current;
    if (!el) return;
    setMore(el.scrollHeight - el.scrollTop - el.clientHeight > END_PX);
  }, []);

  // Content here changes as the session moves through its states, so the hint
  // has to re-measure on resize AND on anything being added or removed.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    for (const child of Array.from(el.children)) observer.observe(child);
    const mutations = new MutationObserver(measure);
    mutations.observe(el, { childList: true, subtree: true });
    return () => { observer.disconnect(); mutations.disconnect(); };
  }, [measure]);

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      <div
        ref={box}
        onScroll={measure}
        className={`console-scroll min-h-0 min-w-0 flex-1 overflow-y-auto ${className}`}
      >
        {children}
      </div>

      {more && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 flex h-10 items-end justify-center bg-gradient-to-t from-[var(--background)] to-transparent"
        >
          <span className="mono pb-1 text-[10px] uppercase tracking-[0.08em] text-[var(--muted)]">
            more below ↓
          </span>
        </div>
      )}
      {/* Said once, politely, for anyone not seeing the gradient. */}
      <span className="sr-only" role="status">
        {more ? "There is more content below. Scroll to see it." : ""}
      </span>
    </div>
  );
}
