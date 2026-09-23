/**
 * A tab strip.
 *
 * Follows the ARIA Authoring Practices tabs pattern with automatic activation:
 * one tab in the tab order, arrow keys move between them, Home and End jump to
 * the ends. Automatic rather than manual activation because every panel here is
 * already mounted and cheap to show — there is nothing to wait for.
 */

import { useRef, type ReactNode } from "react";

export type TabDef<K extends string> = {
  key: K;
  label: string;
  /** A count or a dot beside the label — a live indicator, not decoration. */
  badge?: ReactNode;
};

export function Tabs<K extends string>({
  tabs, active, onSelect, label, id, action,
}: {
  tabs: readonly TabDef<K>[];
  active: K;
  onSelect: (key: K) => void;
  /** Names the tab list for a screen reader — "Console view", not "Tabs". */
  label: string;
  /** Prefix for the tab and panel ids, so aria-controls can point at them. */
  id: string;
  /** Something on the right of the strip: a Clear button, a live badge. */
  action?: ReactNode;
}) {
  const strip = useRef<HTMLDivElement>(null);

  const move = (delta: number | "home" | "end") => {
    const index = tabs.findIndex((t) => t.key === active);
    const next =
      delta === "home" ? 0
      : delta === "end" ? tabs.length - 1
      : (index + delta + tabs.length) % tabs.length;
    onSelect(tabs[next].key);
    // Focus follows selection, or the arrow keys would move the highlight away
    // from the keyboard.
    strip.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  };

  return (
    <div className="flex items-stretch justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface)]">
      <div
        ref={strip}
        role="tablist"
        aria-label={label}
        className="flex min-w-0 items-stretch"
        onKeyDown={(event) => {
          const key = event.key;
          if (key === "ArrowRight") { event.preventDefault(); move(1); }
          else if (key === "ArrowLeft") { event.preventDefault(); move(-1); }
          else if (key === "Home") { event.preventDefault(); move("home"); }
          else if (key === "End") { event.preventDefault(); move("end"); }
        }}
      >
        {tabs.map((tab) => {
          const current = tab.key === active;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              id={`${id}-tab-${tab.key}`}
              aria-selected={current}
              aria-controls={`${id}-panel-${tab.key}`}
              tabIndex={current ? 0 : -1}
              onClick={() => onSelect(tab.key)}
              className={`flex min-h-10 items-center gap-2 px-4 text-xs font-semibold uppercase tracking-[0.07em] transition-colors ${
                current
                  ? "bg-[var(--surface-2)] text-[var(--heading)] shadow-[inset_0_-2px_0_var(--primary)]"
                  : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
              }`}
            >
              {tab.label}
              {tab.badge}
            </button>
          );
        })}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2 px-3">{action}</div>}
    </div>
  );
}

/** The panel half of the pair. Hidden rather than unmounted, so scroll and
 *  autoscroll position survive a tab switch. */
export function TabPanel({
  id, tabKey, active, children, className = "",
}: {
  id: string;
  tabKey: string;
  active: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="tabpanel"
      id={`${id}-panel-${tabKey}`}
      aria-labelledby={`${id}-tab-${tabKey}`}
      hidden={!active}
      className={active ? className : "hidden"}
    >
      {children}
    </div>
  );
}
