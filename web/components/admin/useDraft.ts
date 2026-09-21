"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Keeps an editor's unsaved work in the browser so a failed save, a crash, a
 * closed tab or an expired session cannot destroy it.
 *
 * PARITY: ../doctor-portfolio/components/admin/useDraft.ts — copied whole; only
 * the storage prefix changed. It was written there and never wired up; here it
 * is wired into every editor, because this repo hit the failure it describes:
 * on 2026-09-21 a save coincided with a server read throwing, the admin had no
 * error boundary, and the page was replaced mid-edit — taking the writing with
 * it.
 *
 * The admin previously kept everything in React state alone, so anything that
 * unmounted the page — an error boundary, a reload, the browser's own error
 * page — took the typing with it. A draft is written to localStorage as you
 * type and only cleared once a save is CONFIRMED (a write that actually
 * changed rows, see lib/mutations.ts), so an optimistic "Saved ✓" can never
 * discard it either.
 *
 * Scoped per record: `key` should include the entity and its id.
 * Drafts older than a week are dropped on read — stale enough to be noise.
 */
const PREFIX = "cropwatcher-draft:";
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

type Stored<T> = { value: T; savedAt: number };

function read<T>(key: string): Stored<T> | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored<T>;
    if (!parsed || typeof parsed.savedAt !== "number") return null;
    if (Date.now() - parsed.savedAt > MAX_AGE_MS) {
      localStorage.removeItem(PREFIX + key);
      return null;
    }
    return parsed;
  } catch {
    // Private mode, blocked storage, or corrupt JSON — never fatal.
    return null;
  }
}

export type Draft<T> = {
  /** A draft found on mount that differs from what the server sent. */
  pending: { value: T; savedAt: number } | null;
  /** True once the value has diverged from what was last saved. */
  dirty: boolean;
  /** Drop the stored draft (after a confirmed save, or on the user's request). */
  discard: () => void;
  /** Mark the current value as the saved baseline and clear the draft. */
  markSaved: () => void;
};

export function useDraft<T>(key: string, value: T, ready = true): Draft<T> {
  const [pending, setPending] = useState<Draft<T>["pending"]>(null);
  const [dirty, setDirty] = useState(false);
  const baseline = useRef<string>(JSON.stringify(value));
  const loaded = useRef(false);

  // On mount: surface a stored draft only when it differs from the server copy.
  useEffect(() => {
    if (!ready || loaded.current) return;
    loaded.current = true;
    const stored = read<T>(key);
    if (stored && JSON.stringify(stored.value) !== baseline.current) {
      setPending(stored);
    }
  }, [key, ready]);

  // Persist as the value changes. Debounced: typing should not hit storage on
  // every keystroke, and 400ms is short enough that a crash loses nothing.
  useEffect(() => {
    if (!ready) return;
    const serialised = JSON.stringify(value);
    const isDirty = serialised !== baseline.current;
    setDirty(isDirty);
    if (!isDirty) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(
          PREFIX + key,
          JSON.stringify({ value, savedAt: Date.now() } satisfies Stored<T>),
        );
      } catch {
        // Quota or private mode: the in-memory state is still intact.
      }
    }, 400);
    return () => clearTimeout(t);
  }, [key, value, ready]);

  // The browser's own guard, for a closed tab or a navigation away.
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const discard = useCallback(() => {
    try {
      localStorage.removeItem(PREFIX + key);
    } catch {
      /* ignore */
    }
    setPending(null);
  }, [key]);

  const markSaved = useCallback(() => {
    baseline.current = JSON.stringify(value);
    setDirty(false);
    discard();
  }, [value, discard]);

  return { pending, dirty, discard, markSaved };
}

/** Human "3 minutes ago" for the restore banner. */
export function timeAgo(ts: number): string {
  const s = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return `${s} second${s === 1 ? "" : "s"} ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}
