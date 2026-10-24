/**
 * The base stations on the room map — where each stands, which way it faces
 * (2026-10-24, Samuel: "put it accurately in the software, so that we know
 * where the base station is, both in the real world and in the software").
 *
 * The places are the drone's own stored geometry (agent /station/poses):
 * exactly what it positions against, so the tripods are as right as the last
 * measurement (② Position) — and only that. They are not tracked: a station
 * moved since is drawn where it WAS until it is measured again.
 */

import { useEffect, useState } from "react";
import { api, type StationMarker } from "@/lib/agent";

/** How often the stations are asked for. The agent reads them from the drone
 *  once per link and after each measure, so this is cheap. */
const EVERY_MS = 5000;

export function useStationMarkers(enabled: boolean): StationMarker[] {
  const [stations, setStations] = useState<StationMarker[]>([]);
  useEffect(() => {
    if (!enabled) { setStations([]); return; }
    let live = true;
    const ask = () => api.stationPoses()
      .then((r) => { if (live) setStations(r.stations); })
      // No agent, no drone, nothing measured: no tripods — never stale ones.
      .catch(() => { if (live) setStations([]); });
    void ask();
    const timer = window.setInterval(() => void ask(), EVERY_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [enabled]);
  return stations;
}

/** "Ch 1", or the station's number when the channel is unknown. */
export function stationLabel(s: StationMarker): string {
  return s.channel !== null ? `Ch ${s.channel}` : `Station ${s.id ?? "?"}`;
}

/** The field of view's four edge directions, in room terms: Valve's published
 *  150° × 110° for Base Station 2.0 (coverage.py FOV_HALF_H/V_DEG). */
export function fovEdges(s: StationMarker): [number, number, number][] {
  const h = (75 * Math.PI) / 180;
  const v = (55 * Math.PI) / 180;
  return [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([sh, sv]) => {
    const ty = Math.tan(h) * sh;
    const tz = Math.tan(v) * sv;
    const n = Math.hypot(1, ty, tz);
    return [0, 1, 2].map((i) => (s.forward[i] + s.left[i] * ty + s.up[i] * tz) / n) as [number, number, number];
  });
}
