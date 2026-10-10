"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useState } from "react";
import { HOME, OPERATOR_HOME } from "@/lib/routes";
import { OPERATOR_GROUPS, activeHref } from "./nav-items";
import { ProfileMenu, type OperatorAccount } from "./ProfileMenu";
import { ThemeToggle } from "@/components/site/ThemeToggle";
import { Wordmark } from "@/components/site/Wordmark";
import { Drawer, MenuButton } from "@/components/ui/drawer";
import { NotificationBell } from "./notifications";

/**
 * The phone and tablet version of the operator sidebar (below 1024 px).
 *
 * A bar — wordmark, theme switch, menu button — and the sidebar itself in a
 * drawer (components/ui/drawer.tsx), its groups as collapsible sections: the
 * group holding the current page opens, the others stay folded, so twelve
 * links do not fill a phone screen. It replaced a sideways-scrolling row of
 * every page, which hid most of them past the edge (2026-09-28).
 */
export function OperatorMobileNav({ account, isOperator }: { account: OperatorAccount | null; isOperator: boolean }) {
  const pathname = usePathname();
  const groups = OPERATOR_GROUPS.filter((g) => !g.operatorOnly || isOperator);
  const active = activeHref(pathname, groups);
  const [open, setOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(pathname);
  const close = useCallback(() => setOpen(false), []);

  // Close on navigation.
  if (open && pathname !== openedAt) setOpen(false);

  return (
    <div className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur-md lg:hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-2">
        <Link href={OPERATOR_HOME} aria-label="DroneDeck — dashboard home" className="flex min-h-11 items-center">
          <Wordmark />
        </Link>
        <div className="flex items-center gap-1">
          <NotificationBell />
          <ThemeToggle />
          <MenuButton
            controls="operator-menu"
            open={open}
            onOpen={() => {
              setOpenedAt(pathname);
              setOpen(true);
            }}
          />
        </div>
      </div>

      <Drawer
        id="operator-menu"
        label="Dashboard menu"
        open={open}
        onClose={close}
        footer={
          <div className="space-y-2">
            <Link href={HOME} className="flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]">
              View site
            </Link>
            {account && <ProfileMenu account={account} placement="up" />}
          </div>
        }
      >
        <nav aria-label="Operator" className="space-y-2">
          {groups.map((group) => {
            const holdsCurrent = group.items.some((item) => item.href === active);
            return (
              <details key={group.label} open={holdsCurrent || groups.length === 1} className="group rounded-xl">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between rounded-lg px-3 text-left [&::-webkit-details-marker]:hidden">
                  <span className="eyebrow">{group.label}</span>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"
                       className="h-4 w-4 text-[var(--muted)] transition-transform group-open:rotate-180">
                    <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
                  </svg>
                </summary>
                <ul className="mt-1 space-y-0.5">
                  {group.items.map((item) => {
                    const current = item.href === active;
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={current ? "page" : undefined}
                          className={`flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium ${
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
              </details>
            );
          })}
        </nav>
      </Drawer>
    </div>
  );
}
