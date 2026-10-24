/**
 * Which base stations the drone hears now — for the Stations vital and the
 * command log (2026-10-24, Samuel: "we are able to detect the two base
 * stations" — on screen, before and during a manual flight).
 *
 * FROM THE LIVE STREAM, OVER A WINDOW. lighthouse.bsReceive is one bit per
 * station (bit n = the firmware's station n, channel n + 1), set when a sweep
 * from it was decoded since the last read. It flickers sample to sample even
 * when reception is fine — the 2026-10-24 Auto flights read 0, 1, 2 and 3 in
 * turn with both stations in view — so a station counts as heard if any
 * sample in the last HEARD_WINDOW_S had its bit. bsGeoVal says which have a
 * stored position (② Position); a station is listed if either is set.
 */

import { useEffect, useRef, useState } from "react";
import type { Telemetry } from "@/lib/agent";

/** Long enough to bridge the flicker at 10 Hz, short enough that a station
 *  blocked by a hand reads lost within a breath. */
export const HEARD_WINDOW_S = 2;

export type StationsHeard = {
  /** Station ids measured or heard, ascending. */
  known: number[];
  /** Of those, heard in the window. */
  heard: number[];
  /** Ids with a stored position. */
  measured: number[];
  /** Light reaches at least one of the deck's four sensors. */
  light: boolean;
};

export const bits = (mask: number | undefined): number[] =>
  mask ? [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15].filter((i) => (mask >> i) & 1) : [];

/** "Ch 1", from a firmware station id. */
export const channelOf = (id: number) => `Ch ${id + 1}`;

/** The stations heard over the last window; null while there is no stream. */
export function useStationsHeard(telemetry: Telemetry | null): StationsHeard | null {
  const recent = useRef<{ at: number; mask: number }[]>([]);
  const [heard, setHeard] = useState<StationsHeard | null>(null);
  useEffect(() => {
    if (!telemetry) {
      recent.current = [];
      setHeard(null);
      return;
    }
    const v = telemetry.values;
    const now = telemetry.at;                      // seconds (session.py time.time())
    recent.current = [...recent.current.filter((s) => now - s.at < HEARD_WINDOW_S),
                      { at: now, mask: v["lighthouse.bsReceive"] ?? 0 }];
    const any = recent.current.reduce((m, s) => m | s.mask, 0);
    const measured = bits(v["lighthouse.bsGeoVal"]);
    const heardIds = bits(any);
    const known = [...new Set([...measured, ...heardIds])].sort((a, b) => a - b);
    const light = [0, 1, 2, 3].some((i) => (v[`lighthouse.width${i}`] ?? 0) > 0);
    const next = { known, heard: heardIds, measured, light };
    setHeard((was) => (was && same(was, next) ? was : next));
  }, [telemetry]);
  return heard;
}

function same(a: StationsHeard, b: StationsHeard): boolean {
  return a.light === b.light && a.known.join() === b.known.join() && a.heard.join() === b.heard.join()
    && a.measured.join() === b.measured.join();
}
