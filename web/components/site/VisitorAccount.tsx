"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { signOut } from "@/lib/mutations";
import { LOGIN, OPERATOR_HOME } from "@/lib/routes";

type Account = { email: string; name: string | null; role: string } | null;

/**
 * The right side of the visitor navbar.
 *
 * Signing in keeps you on the visitor site — the operator screens open only from
 * Dashboard. Dashboard is a protected route, so a signed-out visitor who clicks it
 * is sent to sign in first and lands on the dashboard afterwards (middleware.ts).
 */
export function VisitorAccount({ account }: { account: Account }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onClick); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const dashboard = (
    <Link href={OPERATOR_HOME}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--primary)] px-4 text-sm font-semibold text-[var(--on-primary)] transition-opacity hover:opacity-90">
      Dashboard
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M13 6l6 6-6 6" />
      </svg>
    </Link>
  );

  if (!account) {
    return (
      <div className="flex items-center gap-2">
        <Link href={`${LOGIN}?next=${encodeURIComponent(pathname || "/")}`}
              className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-[var(--muted)] hover:text-[var(--foreground)]">
          Sign in
        </Link>
        {dashboard}
      </div>
    );
  }

  const initial = (account.name || account.email).trim().charAt(0).toUpperCase();
  return (
    <div className="flex items-center gap-2">
      {dashboard}
      <div ref={root} className="relative">
        <button type="button" aria-haspopup="menu" aria-expanded={open}
                aria-label={`Account: ${account.email}`} onClick={() => setOpen((v) => !v)}
                className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--surface-2)] text-sm font-semibold ring-1 ring-[var(--border)]">
          {initial}
        </button>
        {open && (
          <div role="menu" className="absolute right-0 top-13 z-40 w-64 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg">
            <div className="border-b border-[var(--border)] p-4">
              {account.name && account.name !== account.email && <p className="truncate font-medium">{account.name}</p>}
              <p className="wrap-anywhere text-sm text-[var(--muted)]">{account.email}</p>
              <p className="eyebrow mt-1">{account.role}</p>
            </div>
            <form action={signOut} className="p-2">
              <button type="submit" role="menuitem"
                      className="flex min-h-10 w-full items-center rounded-lg px-3 text-left text-sm font-medium text-[var(--status-critical)] hover:bg-[var(--surface-2)]">
                Sign out
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
