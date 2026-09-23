/**
 * The window's left rail.
 *
 * Copy-adapted from `web/components/operator/OperatorSidebar.tsx`: brand at the
 * top, the pages in groups, then the way out and the account at the foot. The
 * two products navigate the same way on purpose.
 *
 * THREE STATES, which is the part the web app does not have:
 *
 *   locked expanded    full width, holds the layout open
 *   locked collapsed   icons only, and the layout keeps the narrow width
 *   hover              collapsed in the LAYOUT, expanded OVER the page
 *
 * The hover state expands as an overlay rather than by widening, so crossing
 * the rail with the pointer never reflows the Control page's two columns. The
 * layout footprint is always the locked width; only the painted aside grows.
 *
 * HOVER IS SUPPRESSED WHILE FLYING. Expanded, the rail covers the left console
 * — the command log and the vitals tail — which is exactly what an operator is
 * watching while the drone is in the air. A rail that opens itself over live
 * telemetry is a hazard, so while a flight is running only the locked states
 * apply and the pin still works.
 *
 * What the desktop forces to change from the web original:
 *
 * - **Square.** Every radius is 0 here (see --radius-* in styles.css).
 * - **The Auto/Manual toggle lives here**, under the brand. It is a mode, not
 *   an action, so it belongs with navigation.
 * - **Flight actions do NOT live here.** Land and Emergency stop are in
 *   FlightStrip, because a nav rail scrolls and an abort control must not.
 * - Buttons, not links: this app has no router.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Mode, Session } from "@/lib/agent";
import type { Page } from "@/App";
import { NAV_GROUPS } from "@/components/nav-items";
import { ProfileMenu } from "@/components/ProfileMenu";
import { openDashboard } from "@/lib/web";

type Locked = "expanded" | "collapsed";

const STORE_KEY = "cropwatcher.sidebar";

/**
 * The pinned state, remembered per machine.
 *
 * localStorage is the right home for this and the wrong home for anything else:
 * it is a per-viewer convenience, it never leaves this browser profile, and a
 * private window or cleared site data can make it throw or come back empty.
 * Every read and write is guarded and the default is a usable state.
 */
function loadLocked(): Locked {
  try {
    return localStorage.getItem(STORE_KEY) === "collapsed" ? "collapsed" : "expanded";
  } catch {
    return "expanded";
  }
}

export function Sidebar({
  page, onNavigate, session, starting, flying, onSetMode, onSignOut,
}: {
  page: Page;
  onNavigate: (page: Page) => void;
  session: Session | null;
  starting: boolean;
  /** While true the rail will not open itself — see the note above. */
  flying: boolean;
  onSetMode: (mode: Mode) => void;
  onSignOut: () => void;
}) {
  const [locked, setLocked] = useState<Locked>(loadLocked);
  const [hovered, setHovered] = useState(false);
  const leaveTimer = useRef<number | null>(null);

  useEffect(() => {
    try { localStorage.setItem(STORE_KEY, locked); } catch { /* private window */ }
  }, [locked]);

  // A flight starting while the rail is hovered open must close it, or it sits
  // over the console for as long as the pointer happens to rest there.
  useEffect(() => {
    if (flying) setHovered(false);
  }, [flying]);

  const expanded = locked === "expanded" || (hovered && !flying);

  // A small grace on leave: crossing a 3.25rem rail diagonally otherwise
  // flickers it shut between two nav rows.
  const onLeave = useCallback(() => {
    if (leaveTimer.current !== null) window.clearTimeout(leaveTimer.current);
    leaveTimer.current = window.setTimeout(() => setHovered(false), 120);
  }, []);
  const onEnter = useCallback(() => {
    if (leaveTimer.current !== null) window.clearTimeout(leaveTimer.current);
    setHovered(true);
  }, []);
  useEffect(() => () => {
    if (leaveTimer.current !== null) window.clearTimeout(leaveTimer.current);
  }, []);

  const modeLocked = starting || session?.state === "busy";

  return (
    // The LAYOUT box: always the locked width, so expanding never reflows.
    <div
      className="relative shrink-0"
      style={{ width: locked === "expanded" ? "var(--sidebar-w)" : "var(--sidebar-w-collapsed)" }}
      onMouseEnter={locked === "collapsed" ? onEnter : undefined}
      onMouseLeave={locked === "collapsed" ? onLeave : undefined}
    >
      <aside
        // The PAINTED box: absolute, so at collapsed width the expanded rail
        // floats above the page instead of pushing it.
        className={`absolute inset-y-0 left-0 z-40 flex flex-col border-r border-[var(--border)] bg-[var(--surface)] ${
          locked === "collapsed" && expanded ? "shadow-2xl" : ""
        }`}
        style={{
          width: expanded ? "var(--sidebar-w)" : "var(--sidebar-w-collapsed)",
          transition: "width 120ms ease",
        }}
      >
        {/* Brand + the pin. Fraunces lives here and nowhere else in the app. */}
        <div className="flex items-center gap-2 px-2 py-3">
          <button
            type="button"
            onClick={() => onNavigate("home")}
            aria-label="CropWatcher — go to Home"
            className="flex min-w-0 items-center gap-2.5"
          >
            <span className="font-display flex h-8 w-8 shrink-0 items-center justify-center bg-[var(--primary)] text-base font-semibold text-[var(--on-primary)]">
              C
            </span>
            {expanded && <span className="font-display truncate text-base font-semibold">CropWatcher</span>}
          </button>
          {expanded && (
            <button
              type="button"
              onClick={() => setLocked(locked === "expanded" ? "collapsed" : "expanded")}
              aria-pressed={locked === "expanded"}
              title={locked === "expanded" ? "Collapse the sidebar" : "Keep the sidebar open"}
              className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                {locked === "expanded"
                  ? <path strokeLinecap="round" strokeLinejoin="round" d="M15 5l-7 7 7 7" />
                  : <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />}
              </svg>
            </button>
          )}
        </div>

        <div className={expanded ? "px-3 pb-3" : "px-2 pb-3"}>
          {expanded && <p className="eyebrow pb-1.5">Flight mode</p>}
          <div
            role="group"
            aria-label="Flight mode"
            className={`flex border border-[var(--border)] ${expanded ? "" : "flex-col"}`}
          >
            {(["auto", "manual"] as Mode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={session?.mode === mode}
                disabled={modeLocked}
                title={
                  modeLocked ? "Finish the current flight first"
                    : expanded ? undefined : `${mode} mode`
                }
                onClick={() => onSetMode(mode)}
                className={`min-h-8 flex-1 text-[10px] font-semibold uppercase tracking-[0.08em] disabled:cursor-not-allowed disabled:opacity-50 ${
                  session?.mode === mode
                    ? "bg-[var(--primary)] text-[var(--on-primary)]"
                    : "text-[var(--muted)] hover:bg-[var(--surface-2)]"
                }`}
              >
                {expanded ? mode : mode.charAt(0).toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <nav aria-label="Pages" className="console-scroll flex-1 space-y-4 overflow-y-auto overflow-x-hidden px-2 pb-3">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              {expanded
                ? <p className="eyebrow px-2 pb-1.5">{group.label}</p>
                : <div aria-hidden="true" className="mx-2 mb-1.5 border-t border-[var(--border)]" />}
              <ul>
                {group.items.map((item) => {
                  const current = page === item.key;
                  return (
                    <li key={item.key}>
                      <button
                        type="button"
                        aria-current={current ? "page" : undefined}
                        onClick={() => onNavigate(item.key)}
                        // Collapsed, the label is the accessible name and the
                        // native tooltip — an icon alone names nothing.
                        title={expanded ? undefined : item.label}
                        aria-label={item.label}
                        className={`flex min-h-9 w-full items-center gap-2.5 px-2 text-left text-sm font-medium transition-colors ${
                          current
                            ? "bg-[var(--surface-2)] text-[var(--heading)] shadow-[inset_3px_0_0_var(--primary)]"
                            : "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        <svg viewBox="0 0 24 24" fill="currentColor" className="h-[18px] w-[18px] shrink-0" aria-hidden="true">
                          <path d={item.icon} />
                        </svg>
                        {expanded && <span className="truncate">{item.label}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-[var(--border)] p-2">
          {/* The web sidebar's "View site" slot. Here it is the dashboard. */}
          <button
            type="button"
            onClick={() => void openDashboard("/app")}
            title="Open the dashboard"
            aria-label="Open the dashboard"
            className="flex min-h-9 w-full items-center gap-2.5 px-2 text-left text-sm font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-[18px] w-[18px] shrink-0" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M14 5h5v5M19 5l-7 7M10 5H6a1 1 0 00-1 1v12a1 1 0 001 1h12a1 1 0 001-1v-4" />
            </svg>
            {expanded && <span className="truncate">Open the dashboard</span>}
          </button>
          <ProfileMenu
            session={session}
            placement="up"
            wide={expanded}
            onSignIn={() => onNavigate("home")}
            onSignOut={onSignOut}
          />
          {/* Collapsed, the pin has nowhere in the header to live. */}
          {!expanded && (
            <button
              type="button"
              onClick={() => setLocked("expanded")}
              title="Keep the sidebar open"
              aria-label="Keep the sidebar open"
              className="mt-1 flex h-8 w-full items-center justify-center text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          )}
        </div>
      </aside>
    </div>
  );
}
