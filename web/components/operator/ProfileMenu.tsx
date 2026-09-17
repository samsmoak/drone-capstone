"use client";

import { useEffect, useRef, useState } from "react";
import { signOut } from "@/lib/mutations";

export type OperatorAccount = { email: string; name: string | null; role: string };

/**
 * The account button: an initial, opening to the full email, role and Sign out.
 * `placement` is "up" at the foot of the sidebar and "down" in the phone bar.
 */
export function ProfileMenu({ account, placement = "up", compact = false }: {
  account: OperatorAccount;
  placement?: "up" | "down";
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const initial = (account.name || account.email).trim().charAt(0).toUpperCase();

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onClick); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${account.email}`}
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center gap-3 rounded-xl text-left transition-colors hover:bg-[var(--surface-2)] ${compact ? "p-1" : "px-3 py-2.5"}`}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-sm font-semibold text-[var(--on-primary)]">
          {initial}
        </span>
        {!compact && (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{account.name && account.name !== account.email ? account.name : "Account"}</span>
            <span className="block truncate text-xs capitalize text-[var(--muted)]">{account.role}</span>
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className={`absolute z-50 w-64 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-xl ${
            placement === "up" ? "bottom-full left-0 mb-2" : "right-0 top-full mt-2"
          }`}
        >
          <div className="border-b border-[var(--border)] p-4">
            {account.name && account.name !== account.email && <p className="truncate font-medium">{account.name}</p>}
            <p className="wrap-anywhere text-sm text-[var(--muted)]">{account.email}</p>
            <p className="eyebrow mt-1">{account.role}</p>
          </div>
          <form action={signOut} className="p-2">
            <button type="submit" role="menuitem"
                    className="flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-[var(--status-critical)] hover:bg-[var(--surface-2)]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4-4-4M21 12H9M13 4H6a2 2 0 00-2 2v12a2 2 0 002 2h7" />
              </svg>
              Sign out
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
