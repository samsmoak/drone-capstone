"use client";

import { create } from "zustand";
import type { TelemetryRow } from "@/lib/queries";

/**
 * Ephemeral live state, and nothing else.
 *
 * The rule from CLAUDE.md: **Zustand holds only ephemeral live state.**
 * Anything persistent comes from Supabase through `lib/queries.ts`. A row that
 * arrives here is already in Postgres — this is a window onto the stream, not
 * a copy of the record. Nothing here survives a reload, and nothing should
 * need to.
 */

/** Whether the live feed is actually delivering. */
export type FeedStatus = "idle" | "connecting" | "live" | "error";

/**
 * How many rows to keep in memory.
 *
 * At 10 Hz this is five minutes of flight — longer than the drone's endurance,
 * which is the point: the buffer covers a whole flight without an unbounded
 * array growing behind a tab someone left open for a day.
 */
export const BUFFER_LIMIT = 3000;

type LiveState = {
  rows: TelemetryRow[];
  status: FeedStatus;
  /** Set when `status` is "error", so the surface can say what failed. */
  error: string | null;
  flightId: string | null;

  push: (row: TelemetryRow) => void;
  /** Start a flight's buffer from rows already stored, before the stream adds to it. */
  reset: (flightId: string | null, initial?: TelemetryRow[]) => void;
  setStatus: (status: FeedStatus, error?: string) => void;
};

export const useLiveStore = create<LiveState>((set) => ({
  rows: [],
  status: "idle",
  error: null,
  flightId: null,

  push: (row) =>
    set((state) => {
      // Realtime gives at-least-once delivery, so the same row can arrive
      // twice. Charting a duplicate draws a spurious spike backwards in time.
      if (state.rows.some((existing) => existing.id === row.id)) return state;

      // Rows can arrive out of order. Appending one blindly draws the line
      // back in time; insert it where its index says it belongs.
      const rows = [...state.rows];
      let at = rows.length;
      while (at > 0 && rows[at - 1].index > row.index) at--;
      rows.splice(at, 0, row);
      return {
        rows: rows.length > BUFFER_LIMIT ? rows.slice(-BUFFER_LIMIT) : rows,
      };
    }),

  reset: (flightId, initial = []) =>
    set({ rows: initial.slice(-BUFFER_LIMIT), flightId, error: null }),

  setStatus: (status, error) =>
    set({ status, error: status === "error" ? (error ?? "Unknown error") : null }),
}));

/* ── manual control ───────────────────────────────────────────────────── */

/** Held-key state. Mirrors `Intent` in `backend/agent/cropwatcher/api/manual.py` field for field. */
export type Intent = {
  up: boolean;
  down: boolean;
  forward: boolean;
  back: boolean;
  left: boolean;
  right: boolean;
  yaw_left: boolean;
  yaw_right: boolean;
};

export const EMPTY_INTENT: Intent = {
  up: false,
  down: false,
  forward: false,
  back: false,
  left: false,
  right: false,
  yaw_left: false,
  yaw_right: false,
};

export type SocketStatus = "disconnected" | "connecting" | "ready" | "error";

type ManualState = {
  socket: SocketStatus;
  /** What the agent's controller reports: idle, flying, landing, stopped. */
  controlState: string;
  thrust: number;
  intent: Intent;
  message: string | null;

  setSocket: (socket: SocketStatus, message?: string | null) => void;
  setReport: (controlState: string, thrust?: number) => void;
  setIntent: (intent: Intent) => void;
};

export const useManualStore = create<ManualState>((set) => ({
  socket: "disconnected",
  controlState: "idle",
  thrust: 0,
  intent: EMPTY_INTENT,
  message: null,

  setSocket: (socket, message = null) => set({ socket, message }),
  setReport: (controlState, thrust) =>
    set((s) => ({ controlState, thrust: thrust ?? s.thrust })),
  setIntent: (intent) => set({ intent }),
}));

/** The most recent row, or null before anything has arrived. */
export function latestRow(rows: TelemetryRow[]): TelemetryRow | null {
  return rows.at(-1) ?? null;
}
