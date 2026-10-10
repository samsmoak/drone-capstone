"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * A tooltip for a highlight: what an anomaly means, on hover, on keyboard
 * focus, and on a tap — never hover alone, which a phone and a keyboard
 * cannot do.
 *
 * WCAG 2.2 1.4.13 (content on hover or focus): it can be dismissed without
 * moving (Escape), the pointer can move onto it without it vanishing (a short
 * grace before it closes), and it stays until the pointer or focus leaves.
 *
 * FIXED, not absolute: the readings table scrolls inside its own box, which
 * would clip a bubble positioned inside it. It follows its anchor when the page
 * or the box scrolls (focusing a thumbnail scrolls it into view), and closes
 * once the anchor has left the screen.
 */

export type HintText = {
  title: string;
  body: string;
  /** "Warning", "Critical", … — said in words beside the colour. */
  label: string;
  color: string;
};

/** The element it points at, and how far along it (the pointer's x on a row). */
type Open = { text: HintText; el: Element; dx: number | null };

const WIDTH = 320;
const GRACE_MS = 150;

export function useHint() {
  const id = useId();
  const [open, setOpen] = useState<Open | null>(null);
  const [, setMoved] = useState(0);
  const closing = useRef<ReturnType<typeof setTimeout> | null>(null);
  // A tap is focus THEN click: the click must not close what the focus just
  // opened.
  const openedAt = useRef(0);

  const cancelClose = useCallback(() => {
    if (closing.current) clearTimeout(closing.current);
    closing.current = null;
  }, []);
  const hide = useCallback(() => {
    cancelClose();
    closing.current = setTimeout(() => setOpen(null), GRACE_MS);
  }, [cancelClose]);
  const hideNow = useCallback(() => { cancelClose(); setOpen(null); }, [cancelClose]);

  /** Open at an element, or at the pointer's x over it. */
  const show = useCallback((text: HintText, el: Element, pointerX?: number) => {
    cancelClose();
    openedAt.current = Date.now();
    setOpen({ text, el, dx: pointerX === undefined ? null : pointerX - el.getBoundingClientRect().left });
  }, [cancelClose]);

  const toggle = useCallback((text: HintText, el: Element) => {
    const same = open && open.text.title === text.title && open.text.body === text.body;
    if (same && Date.now() - openedAt.current > 400) hideNow();
    else if (!same) show(text, el);
  }, [open, show, hideNow]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") hideNow(); };
    // Follow the anchor; close once it is off the screen.
    const onMove = () => {
      const r = open.el.getBoundingClientRect();
      if (!open.el.isConnected || r.bottom < 0 || r.top > window.innerHeight) hideNow();
      else setMoved((n) => n + 1);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open, hideNow]);

  useEffect(() => cancelClose, [cancelClose]);

  const bubble: ReactNode = open ? (
    <Bubble id={id} open={open} onEnter={cancelClose} onLeave={hide} />
  ) : null;
  return { id, isOpen: open !== null, show, hide, hideNow, toggle, bubble };
}

function Bubble({ id, open, onEnter, onLeave }: {
  id: string; open: Open; onEnter: () => void; onLeave: () => void;
}) {
  const { text, el, dx } = open;
  const r = el.getBoundingClientRect();
  const at = { x: dx === null ? r.left + r.width / 2 : r.left + dx, top: r.top, bottom: r.bottom };
  const vw = typeof window === "undefined" ? 1024 : window.innerWidth;
  const vh = typeof window === "undefined" ? 768 : window.innerHeight;
  const width = Math.min(WIDTH, vw - 16);
  const left = Math.max(8, Math.min(at.x - width / 2, vw - width - 8));
  // Below the anchor when there is room for it, above otherwise.
  const below = at.bottom + 180 < vh;
  return (
    <div
      id={id}
      role="tooltip"
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        position: "fixed", left, width,
        top: below ? at.bottom + 8 : at.top - 8,
        transform: below ? undefined : "translateY(-100%)",
        borderLeftColor: text.color,
      }}
      className="z-50 rounded-lg border border-l-4 border-[var(--border)] bg-[var(--surface)] p-3 text-left text-sm text-[var(--foreground)] shadow-lg"
    >
      <p className="flex items-baseline justify-between gap-3">
        <span className="font-semibold">{text.title}</span>
        <span className="shrink-0 text-xs font-medium">{text.label}</span>
      </p>
      <p className="mt-1">{text.body}</p>
    </div>
  );
}
