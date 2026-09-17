"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type NavItem = { readonly href: string; readonly label: string };

/**
 * Shared navigation.
 *
 * `aria-current` marks the active item, so the current page is announced and
 * not signalled by colour alone.
 */
export function Nav({
  items,
  brand,
  brandHref = "/",
  trailing,
}: {
  items: readonly NavItem[];
  brand: string;
  brandHref?: string;
  trailing?: React.ReactNode;
}) {
  const pathname = usePathname();

  // The most specific match wins. A plain prefix test marks "/app" active on
  // every page beneath it, so the dashboard and the real page both claim
  // aria-current and the operator cannot tell where they are.
  const activeHref = items
    .filter(
      (item) =>
        pathname === item.href ||
        (item.href !== "/" && pathname.startsWith(item.href + "/")),
    )
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  return (
    <header className="border-b border-[var(--border)] bg-[var(--surface)]">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3"
      >
        <Link href={brandHref} className="font-semibold tracking-tight">
          {brand}
        </Link>

        <ul className="flex flex-wrap items-center gap-x-1 gap-y-1">
          {items.map((item) => {
            const active = item.href === activeHref;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`inline-flex min-h-11 items-center rounded-md px-3 text-sm ${
                    active
                      ? "bg-[var(--surface-2)] font-medium text-[var(--foreground)]"
                      : "text-[var(--muted)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>

        {trailing && <div className="ml-auto">{trailing}</div>}
      </nav>
    </header>
  );
}
