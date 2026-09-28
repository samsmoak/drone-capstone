"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useState } from "react";
import { Drawer, MenuButton } from "@/components/ui/drawer";
import { SITE_CONTAINER } from "@/lib/layout";

type NavItem = { readonly href: string; readonly label: string };

/**
 * The visitor site's navigation.
 *
 * From 1024 px up it is one row: brand, links, the Dashboard link, then the
 * actions and the account at the far right. Below that it is the brand, the
 * actions and a menu button that opens a drawer from the right with every
 * link, the Dashboard link and the account — a row of seven links wrapped to
 * three lines on a phone before (2026-09-28).
 *
 * The drawer is components/ui/drawer.tsx — a modal dialog shared with the
 * operator sidebar. It closes itself on navigation.
 *
 * `aria-current` marks the active item, so the current page is announced and
 * not signalled by colour alone.
 */
export function Nav({
  items,
  brand,
  brandHref = "/",
  brandLabel,
  actions,
  trailing,
  cta,
  width = SITE_CONTAINER,
  wide,
}: {
  items: readonly NavItem[];
  /** The wordmark, or plain text. */
  brand: React.ReactNode;
  brandHref?: string;
  /** What the brand link is announced as, since the wordmark is partly an image. */
  brandLabel?: string;
  /** Always on the bar, at every width — e.g. the theme switch. */
  actions?: React.ReactNode;
  /** The account: on the bar from 1024 px, in the drawer below it. */
  trailing?: React.ReactNode;
  /** Sits with the links, not out at the far right — it is a destination too. */
  cta?: React.ReactNode;
  /** Container width and padding — must match the page below so the edges line up. */
  width?: string;
  /** Pages that use a wider container, so the bar widens with them. */
  wide?: { prefixes: readonly string[]; width: string };
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(pathname);
  const close = useCallback(() => setOpen(false), []);

  // Close on navigation: a drawer left open over the new page hides it.
  if (open && pathname !== openedAt) setOpen(false);

  const container = wide && wide.prefixes.some((p) => pathname.startsWith(p)) ? wide.width : width;

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

  const link = (item: NavItem, inDrawer: boolean) => {
    const active = item.href === activeHref;
    return (
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        className={`flex min-h-11 items-center rounded-md px-3 text-sm ${inDrawer ? "text-base" : ""} ${
          active
            ? "bg-[var(--surface-2)] font-medium text-[var(--foreground)]"
            : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
        }`}
      >
        {item.label}
      </Link>
    );
  };

  return (
    <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--surface)]">
      <nav aria-label="Main" className={`flex ${container} items-center gap-x-6 py-3`}>
        <Link href={brandHref} aria-label={brandLabel} className="flex min-h-11 shrink-0 items-center font-semibold tracking-tight">
          {brand}
        </Link>

        <ul className="hidden items-center gap-x-1 lg:flex">
          {items.map((item) => <li key={item.href}>{link(item, false)}</li>)}
          {cta && <li className="ml-1">{cta}</li>}
        </ul>

        <div className="ml-auto flex items-center gap-1">
          {actions}
          {trailing && <div className="hidden lg:block">{trailing}</div>}
          <MenuButton
            controls="site-menu"
            open={open}
            onOpen={() => {
              setOpenedAt(pathname);
              setOpen(true);
            }}
            className="lg:hidden"
          />
        </div>
      </nav>

      <Drawer id="site-menu" label="Menu" open={open} onClose={close} footer={trailing}>
        <ul className="space-y-1">
          {items.map((item) => <li key={item.href}>{link(item, true)}</li>)}
          {cta && <li className="pt-2">{cta}</li>}
        </ul>
      </Drawer>
    </header>
  );
}
