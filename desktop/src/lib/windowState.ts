/**
 * A choice that outlives the page it was made on, and not the window.
 *
 * React state belongs to a component, and every page here is unmounted when
 * the sidebar moves to another — so a filter set on Playback came back reset
 * after a visit to Control (2026-10-24, Samuel: "what i select there should be
 * persistent, unless maybe i close and reopen the app").
 *
 * Held in memory only, never in localStorage: closing the app is the reset the
 * owner asked for, and a filter remembered across launches would hide flights
 * on a fresh start without saying why.
 */

import { useCallback, useSyncExternalStore } from "react";

const values = new Map<string, unknown>();
const listeners = new Map<string, Set<() => void>>();

function subscribe(key: string, onChange: () => void): () => void {
  let set = listeners.get(key);
  if (!set) listeners.set(key, (set = new Set()));
  set.add(onChange);
  return () => set.delete(onChange);
}

/** Like useState, but kept under `key` for as long as the window is open. */
export function useWindowState<T>(key: string, initial: T): [T, (next: T) => void] {
  const value = useSyncExternalStore(
    useCallback((onChange: () => void) => subscribe(key, onChange), [key]),
    () => (values.has(key) ? (values.get(key) as T) : initial),
  );
  const set = useCallback((next: T) => {
    values.set(key, next);
    listeners.get(key)?.forEach((l) => l());
  }, [key]);
  return [value, set];
}
