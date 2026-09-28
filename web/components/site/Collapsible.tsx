"use client";

import { useId, useState } from "react";

/**
 * A side menu that folds away on smaller screens and is simply there on large
 * ones.
 *
 * Below the breakpoint it is a full-width toggle, closed at first, so a phone
 * reaches the article instead of scrolling past a contents list and a team
 * list. From the breakpoint up the button is hidden and the content always
 * shows — done in CSS (max-lg:hidden / max-xl:hidden), so a large screen never
 * renders it closed, not even for a frame before hydration.
 */
const BREAKPOINT = {
  lg: { button: "lg:hidden", closed: "max-lg:hidden", gap: "max-lg:mt-3" },
  xl: { button: "xl:hidden", closed: "max-xl:hidden", gap: "max-xl:mt-3" },
} as const;

export function Collapsible({
  label,
  breakpoint = "lg",
  children,
}: {
  label: string;
  breakpoint?: keyof typeof BREAKPOINT;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const bp = BREAKPOINT[breakpoint];

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={id}
        className={`${bp.button} flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-5 text-left text-sm font-medium`}
      >
        {label}
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
          className={`h-5 w-5 shrink-0 text-[var(--muted)] transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
        </svg>
      </button>
      <div id={id} className={open ? bp.gap : bp.closed}>
        {children}
      </div>
    </div>
  );
}
