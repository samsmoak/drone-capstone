"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { HOME, OPERATOR_HOME } from "@/lib/routes";
import { OPERATOR_GROUPS, activeHref } from "./nav-items";
import { ProfileMenu, type OperatorAccount } from "./ProfileMenu";

/**
 * The operator view's left sidebar. Copied from ../doctor-portfolio's
 * AdminSidebar: brand at the top, the pages, then "View site" and the account at
 * the foot — adapted into two groups, and the email and Sign out moved into the
 * account menu.
 */
export function OperatorSidebar({ account, isOperator }: { account: OperatorAccount | null; isOperator: boolean }) {
  const pathname = usePathname();
  const groups = OPERATOR_GROUPS.filter((g) => !g.operatorOnly || isOperator);
  const active = activeHref(pathname, groups);

  return (
    <aside className="flex h-full flex-col">
      <div className="px-5 py-6">
        {/* Home of this view: the dashboard. */}
        <Link href={OPERATOR_HOME} className="flex items-center gap-2.5">
          <span className="font-display flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--primary)] text-lg font-semibold text-[var(--on-primary)]">
            C
          </span>
          <span className="font-display text-lg font-semibold">CropWatcher</span>
        </Link>
      </div>

      <nav aria-label="Operator" className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="eyebrow px-3 pb-2">{group.label}</p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const current = item.href === active;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={current ? "page" : undefined}
                      className={`flex min-h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors ${
                        current
                          ? "bg-[var(--surface-2)] text-[var(--heading)] shadow-[inset_3px_0_0_var(--primary)]"
                          : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5 shrink-0" aria-hidden="true">
                        <path d={item.icon} />
                      </svg>
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="space-y-1 border-t border-[var(--border)] p-3">
        <Link
          href={HOME}
          className="flex min-h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7 7-7M3 12h18" />
          </svg>
          View site
        </Link>
        {account && <ProfileMenu account={account} placement="up" />}
      </div>
    </aside>
  );
}
