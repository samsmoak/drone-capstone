"use client";

import Link from "next/link";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
} from "react";
import type { NotificationRow } from "@/lib/queries";
import { markAllNotificationsRead, markNotificationRead } from "@/lib/mutations";
import { authedRealtimeClient } from "@/lib/realtime";
import { isSupabaseConfigured } from "@/lib/supabase/client";
import { FLIGHTS, NOTIFICATIONS, SESSIONS } from "@/lib/routes";
import { formatLocal, useIsClient } from "@/components/ui/local-time";

/**
 * The operator's notifications: one row per warning-or-worse finding, made by
 * the database (migration 20261009000017) and KEPT UNTIL READ (the owner,
 * 2026-10-09: persistent). The rows are the record; Realtime only makes a new
 * one arrive at once. One subscription for the whole shell — the bell in the
 * sidebar and the one in the phone bar read the same state.
 */

type State = {
  items: NotificationRow[];
  unread: number;
  markRead: (id: string) => void;
  markAllRead: () => void;
  pending: boolean;
  error: string | null;
  announcement: string;
};

const NotificationsContext = createContext<State | null>(null);

/** Where a notification takes you: its finding on the session page. */
export function notificationHref(n: Pick<NotificationRow, "session_id" | "flight_id" | "finding_id">) {
  if (n.session_id) return `${SESSIONS}/${n.session_id}#finding-${n.finding_id}`;
  if (n.flight_id) return `${FLIGHTS}/${n.flight_id}#finding-${n.finding_id}`;
  return NOTIFICATIONS;
}

export function NotificationsProvider({ userId, initial, unread: initialUnread, children }: {
  userId: string;
  initial: NotificationRow[];
  unread: number;
  children: React.ReactNode;
}) {
  const [items, setItems] = useState(initial);
  const [unread, setUnread] = useState(initialUnread);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    let cancelled = false;
    let cleanup: (() => void) | undefined;
    void (async () => {
      const supabase = await authedRealtimeClient();
      if (!supabase || cancelled) return;
      const channel = supabase
        .channel(`notifications:${userId}`)
        .on("postgres_changes",
            { event: "INSERT", schema: "public", table: "notifications", filter: `user_id=eq.${userId}` },
            (payload) => {
              const row = payload.new as NotificationRow;
              setItems((prev) => (prev.some((n) => n.id === row.id) ? prev : [row, ...prev]));
              setUnread((n) => n + 1);
              setAnnouncement(`New ${row.severity}: ${row.title}`);
            })
        .subscribe();
      cleanup = () => { void supabase.removeChannel(channel); };
    })();
    return () => { cancelled = true; cleanup?.(); };
  }, [userId]);

  const markRead = useCallback((id: string) => {
    const target = items.find((n) => n.id === id);
    if (!target || target.read_at) return;
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n)));
    setUnread((n) => Math.max(0, n - 1));
    startTransition(async () => {
      const result = await markNotificationRead(id);
      setError(result.ok ? null : result.error);
    });
  }, [items]);

  const markAllRead = useCallback(() => {
    const now = new Date().toISOString();
    setItems((prev) => prev.map((n) => (n.read_at ? n : { ...n, read_at: now })));
    setUnread(0);
    startTransition(async () => {
      const result = await markAllNotificationsRead();
      setError(result.ok ? null : result.error);
    });
  }, []);

  return (
    <NotificationsContext.Provider value={{ items, unread, markRead, markAllRead, pending, error, announcement }}>
      {children}
      {/* New arrivals are announced once, politely, wherever the operator is. */}
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
    </NotificationsContext.Provider>
  );
}

export function useNotifications(): State | null {
  return useContext(NotificationsContext);
}

const TONE = { critical: "var(--status-critical)", warning: "var(--status-serious)" } as const;

export function NotificationBell({ placement = "below" }: { placement?: "below" | "right" }) {
  const state = useNotifications();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const wrapper = useRef<HTMLDivElement>(null);
  const client = useIsClient();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onClick = (e: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  if (!state) return null;
  const { items, unread, markRead, markAllRead, pending, error } = state;
  const latest = items.slice(0, 8);
  const label = unread === 0 ? "Notifications, none unread" : `Notifications, ${unread} unread`;

  return (
    <div ref={wrapper} className="relative">
      <button type="button" aria-label={label} aria-expanded={open} aria-controls={panelId}
              onClick={() => setOpen((v) => !v)}
              className="relative inline-flex h-11 w-11 items-center justify-center rounded-lg text-[var(--foreground)] hover:bg-[var(--surface-2)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-5 w-5" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round"
                d="M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2a2 2 0 01-.6 1.4L4 17h5m6 0a3 3 0 11-6 0" />
        </svg>
        {unread > 0 && (
          <span aria-hidden="true"
                className="absolute right-1 top-1 min-w-5 rounded-full bg-[var(--status-critical)] px-1 text-center text-[11px] font-semibold leading-5 text-[var(--on-critical)]">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div id={panelId} role="region" aria-label="Notifications"
             // In the phone bar the bell is not at the screen's edge: the
             // panel spans the screen, 16 px gutters, instead of hanging off it.
             className={`z-50 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 shadow-lg ${
               placement === "right"
                 ? "absolute left-0 top-12 w-[22rem]"
                 : "fixed inset-x-4 top-16 sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-[22rem]"}`}>
          <div className="flex items-center justify-between gap-2 pb-2">
            <p className="text-sm font-semibold">{unread === 0 ? "No unread notifications" : `${unread} unread`}</p>
            {unread > 0 && (
              <button type="button" onClick={markAllRead} disabled={pending}
                      className="inline-flex min-h-11 items-center rounded-lg px-2 text-sm underline underline-offset-4 disabled:opacity-50">
                Mark all read
              </button>
            )}
          </div>
          {error && <p role="alert" className="pb-2 text-sm text-[var(--status-critical)]">{error}</p>}
          {latest.length === 0 ? (
            <p className="py-4 text-sm text-[var(--muted)]">
              Nothing yet. A finding of warning or worse in a processed flight lands here, and stays until you read it.
            </p>
          ) : (
            <ul className="max-h-96 space-y-1 overflow-y-auto">
              {latest.map((n) => (
                <li key={n.id}>
                  <Link href={notificationHref(n)}
                        onClick={() => { markRead(n.id); setOpen(false); }}
                        className="block rounded-lg p-2 hover:bg-[var(--surface-2)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]">
                    <span className="flex items-baseline gap-2">
                      <span aria-hidden="true" style={{ color: TONE[n.severity as keyof typeof TONE] ?? "inherit" }}>
                        {n.severity === "critical" ? "■" : "▲"}
                      </span>
                      <span className={`text-sm ${n.read_at ? "" : "font-semibold"}`}>
                        {n.read_at ? "" : <span className="sr-only">Unread. </span>}
                        {n.severity === "critical" ? "Critical" : "Warning"}: {n.title}
                      </span>
                    </span>
                    <span className="mt-0.5 block pl-5 text-xs text-[var(--muted)]">
                      {client ? formatLocal(n.created_at, "short") : n.created_at}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <div className="border-t border-[var(--border)] pt-2">
            <Link href={NOTIFICATIONS} onClick={() => setOpen(false)}
                  className="inline-flex min-h-11 items-center text-sm underline underline-offset-4">
              View all notifications
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
