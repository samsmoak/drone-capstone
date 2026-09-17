/**
 * The account menu in the top bar.
 *
 * The bar shows an initial, not an email address: a full address crowded the
 * pages off the bar at the window's minimum width, and it is not something an
 * operator needs to read every second. The menu shows it in full.
 */

import { useEffect, useRef, useState } from "react";
import type { Session } from "./agent";
import { initialOf } from "./format";

type Props = {
  session: Session | null;
  onSignIn: () => void;
  onSignOut: () => void;
};

export function ProfileMenu({ session, onSignIn, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const operator = session?.operator ?? null;
  const inSession = session != null && !["signed_out", "idle"].includes(session.state);

  // Close on a click outside or Escape — the two ways people dismiss a menu.
  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={operator ? `Account: ${operator.email}` : "Account: not signed in"}
        onClick={() => setOpen((v) => !v)}
        className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold transition-colors ${
          operator
            ? "bg-[var(--primary)] text-[var(--on-primary)]"
            : "border border-[var(--border)] bg-[var(--surface-2)] text-[var(--muted)]"
        }`}
      >
        {operator ? initialOf(operator.name, operator.email) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" strokeLinecap="round" />
          </svg>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-12 z-30 w-72 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg"
        >
          {operator ? (
            <>
              <div className="flex items-center gap-3 border-b border-[var(--border)] p-4">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-base font-semibold text-[var(--on-primary)]">
                  {initialOf(operator.name, operator.email)}
                </span>
                <div className="min-w-0">
                  {operator.name && operator.name !== operator.email && (
                    <p className="truncate font-medium">{operator.name}</p>
                  )}
                  <p className="wrap-anywhere text-sm text-[var(--muted)]">{operator.email}</p>
                  {operator.role && (
                    <p className="eyebrow mt-1">{operator.role}</p>
                  )}
                </div>
              </div>
              <div className="p-2">
                {inSession && (
                  <p className="px-3 pb-2 pt-1 text-xs text-[var(--muted)]">
                    Signing out ends the running session first — landing the drone if it is flying.
                  </p>
                )}
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => { setOpen(false); onSignOut(); }}
                  className="flex min-h-10 w-full items-center rounded-lg px-3 text-left text-sm font-medium text-[var(--status-critical)] hover:bg-[var(--surface-2)]"
                >
                  Sign out
                </button>
              </div>
            </>
          ) : (
            <div className="p-4">
              <p className="font-medium">Not signed in</p>
              <p className="mt-1 text-sm text-[var(--muted)]">
                Sign in with your CropWatcher account to fly. You stay signed in until you sign out.
              </p>
              <button
                type="button"
                role="menuitem"
                onClick={() => { setOpen(false); onSignIn(); }}
                className="mt-3 flex min-h-10 w-full items-center justify-center rounded-lg bg-[var(--primary)] text-sm font-medium text-[var(--on-primary)]"
              >
                Sign in
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
