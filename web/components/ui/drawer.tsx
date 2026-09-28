"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/**
 * A menu that slides in from the right on small screens — the visitor nav's
 * and the operator sidebar's (components/ui/nav.tsx, OperatorMobileNav).
 *
 * A modal dialog: focus moves into it and is kept there, Escape and the
 * backdrop close it, the page behind cannot scroll, and focus goes back to
 * whatever opened it. The caller decides when it is open, and closes it on
 * navigation.
 *
 * Rendered into <body> through a portal, not where it is declared: the
 * operator bar is backdrop-blurred, and a backdrop-filter makes an element the
 * containing block for its fixed descendants — the "full-screen" drawer was
 * pinned inside the 60 px bar, see-through (2026-09-28).
 */
export function Drawer({
  id,
  label,
  open,
  onClose,
  children,
  footer,
}: {
  id: string;
  label: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const focusables = () =>
      [...(panel.current?.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), summary") ?? [])];
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const list = focusables();
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-black/40"
      />
      <div
        ref={panel}
        id={id}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="absolute inset-y-0 right-0 flex w-[min(20rem,85vw)] flex-col border-l border-[var(--border)] bg-[var(--surface)] shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <span className="eyebrow">{label}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the menu"
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-[var(--foreground)] hover:bg-[var(--surface-2)]"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-6 w-6" aria-hidden="true">
              <path strokeLinecap="round" d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">{children}</div>
        {footer && <div className="border-t border-[var(--border)] p-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** The ☰ button that opens a Drawer. */
export function MenuButton({ controls, open, onOpen, className = "" }: {
  controls: string;
  open: boolean;
  onOpen: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-expanded={open}
      aria-controls={controls}
      aria-label="Open the menu"
      className={`inline-flex h-11 w-11 items-center justify-center rounded-lg text-[var(--foreground)] hover:bg-[var(--surface-2)] ${className}`}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-6 w-6" aria-hidden="true">
        <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
      </svg>
    </button>
  );
}
