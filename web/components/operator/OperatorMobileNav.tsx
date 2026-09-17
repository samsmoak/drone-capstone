"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { HOME, OPERATOR_HOME } from "@/lib/routes";
import { OPERATOR_GROUPS, activeHref } from "./nav-items";
import { ProfileMenu, type OperatorAccount } from "./ProfileMenu";

/** The phone and tablet version of the sidebar. Copied from ../doctor-portfolio's AdminMobileNav. */
export function OperatorMobileNav({ account, isOperator }: { account: OperatorAccount | null; isOperator: boolean }) {
  const pathname = usePathname();
  const groups = OPERATOR_GROUPS.filter((g) => !g.operatorOnly || isOperator);
  const items = groups.flatMap((g) => g.items);
  const active = activeHref(pathname, groups);

  return (
    <div className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur-md lg:hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <Link href={OPERATOR_HOME} className="font-display text-lg font-semibold">CropWatcher</Link>
        <div className="flex items-center gap-2">
          <Link href={HOME} className="inline-flex min-h-10 items-center rounded-lg px-3 text-sm font-medium text-[var(--muted)]">
            View site
          </Link>
          {account && <ProfileMenu account={account} placement="down" compact />}
        </div>
      </div>
      <nav aria-label="Operator" className="flex gap-1 overflow-x-auto px-3 pb-2.5">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={item.href === active ? "page" : undefined}
            className={`inline-flex min-h-10 items-center whitespace-nowrap rounded-lg px-3 text-sm font-medium ${
              item.href === active ? "bg-[var(--surface-2)] text-[var(--heading)]" : "text-[var(--muted)]"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
