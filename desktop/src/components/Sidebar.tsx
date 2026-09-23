/**
 * The window's left rail.
 *
 * Copy-adapted from `web/components/operator/OperatorSidebar.tsx`: brand at the
 * top, the pages in groups, then the way out and the account at the foot. The
 * two products navigate the same way on purpose.
 *
 * What the desktop forces to change:
 *
 * - **Square.** Every radius is 0 here (see --radius-* in styles.css). An
 *   instrument panel is square; the marketing site is not.
 * - **The Auto/Manual toggle lives here**, under the brand. It is a mode, not
 *   an action — it belongs with navigation. It used to sit in the top bar.
 * - **Flight actions do NOT live here.** Land and Emergency stop are in
 *   FlightStrip, because a nav rail scrolls and an abort control must not.
 * - Buttons, not links: this app has no router.
 */

import type { Mode, Session } from "@/lib/agent";
import type { Page } from "@/App";
import { NAV_GROUPS } from "@/components/nav-items";
import { ProfileMenu } from "@/components/ProfileMenu";
import { openDashboard } from "@/lib/web";

export function Sidebar({
  page, onNavigate, session, starting, onSetMode, onSignOut,
}: {
  page: Page;
  onNavigate: (page: Page) => void;
  session: Session | null;
  starting: boolean;
  onSetMode: (mode: Mode) => void;
  onSignOut: () => void;
}) {
  // Locked while a flight is running: switching mid-air would hand the drone to
  // a different command source with no warning.
  const modeLocked = starting || session?.state === "busy";

  return (
    <aside
      className="flex h-full flex-col border-r border-[var(--border)] bg-[var(--surface)]"
      style={{ width: "var(--sidebar-w)" }}
    >
      {/* Home of this window. Fraunces lives here and nowhere else in the app
          now — one brand mark, so it still reads as the same product as the
          website without putting a display serif over an instrument panel. */}
      <div className="px-4 py-4">
        <button
          type="button"
          onClick={() => onNavigate("home")}
          aria-label="CropWatcher — go to Home"
          className="flex items-center gap-2.5"
        >
          <span className="font-display flex h-8 w-8 items-center justify-center bg-[var(--primary)] text-base font-semibold text-[var(--on-primary)]">
            C
          </span>
          <span className="font-display text-base font-semibold">CropWatcher</span>
        </button>
      </div>

      <div className="px-4 pb-4">
        <p className="eyebrow pb-1.5">Flight mode</p>
        <div role="group" aria-label="Flight mode" className="flex border border-[var(--border)]">
          {(["auto", "manual"] as Mode[]).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={session?.mode === mode}
              disabled={modeLocked}
              title={session?.state === "busy" ? "Finish the current flight first" : undefined}
              onClick={() => onSetMode(mode)}
              className={`min-h-9 flex-1 text-xs font-semibold uppercase tracking-[0.08em] disabled:cursor-not-allowed disabled:opacity-50 ${
                session?.mode === mode
                  ? "bg-[var(--primary)] text-[var(--on-primary)]"
                  : "text-[var(--muted)] hover:bg-[var(--surface-2)]"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      <nav aria-label="Pages" className="console-scroll flex-1 space-y-5 overflow-y-auto px-2 pb-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            <p className="eyebrow px-2 pb-1.5">{group.label}</p>
            <ul>
              {group.items.map((item) => {
                const current = page === item.key;
                return (
                  <li key={item.key}>
                    <button
                      type="button"
                      aria-current={current ? "page" : undefined}
                      onClick={() => onNavigate(item.key)}
                      className={`flex min-h-9 w-full items-center gap-2.5 px-2 text-left text-sm font-medium transition-colors ${
                        current
                          ? "bg-[var(--surface-2)] text-[var(--heading)] shadow-[inset_3px_0_0_var(--primary)]"
                          : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      <svg viewBox="0 0 24 24" fill="currentColor" className="h-[18px] w-[18px] shrink-0" aria-hidden="true">
                        <path d={item.icon} />
                      </svg>
                      {item.label}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-[var(--border)] p-2">
        {/* The web sidebar's "View site" slot. Here it is the dashboard: the
            flights from every laptop, not just this one's. */}
        <button
          type="button"
          onClick={() => void openDashboard("/app")}
          className="flex min-h-9 w-full items-center gap-2.5 px-2 text-left text-sm font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-[18px] w-[18px] shrink-0" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M14 5h5v5M19 5l-7 7M10 5H6a1 1 0 00-1 1v12a1 1 0 001 1h12a1 1 0 001-1v-4" />
          </svg>
          Open the dashboard
        </button>
        <ProfileMenu
          session={session}
          placement="up"
          wide
          onSignIn={() => onNavigate("home")}
          onSignOut={onSignOut}
        />
      </div>
    </aside>
  );
}
