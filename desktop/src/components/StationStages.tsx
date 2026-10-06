/**
 * The base station as the drone sees it — shared by Set up (step 3, channels)
 * and Auto › ② Position, so both say the same thing in the same words.
 *
 * One row per stage between the station's light and a position, in the order
 * the drone needs them: the first row that is not ✓ is the one to fix
 * (agent session.station_status; firmware log names in docs/features/desktop/
 * setup.txt).
 */

import { useEffect, useState } from "react";
import { api, type StationStatus } from "@/lib/agent";
import { StatusDot } from "@/components/ui";

/** How often the base station's status is re-read. */
const STATION_EVERY_MS = 1000;

/** The base station's status, re-read every second while the drone is connected. */
export function useStation(connected: boolean): StationStatus | null {
  const [status, setStatus] = useState<StationStatus | null>(null);
  useEffect(() => {
    if (!connected) { setStatus(null); return; }
    let live = true;
    const ask = () => {
      api.stationStatus().then((s) => { if (live) setStatus(s); }).catch(() => {});
    };
    ask();
    const timer = window.setInterval(ask, STATION_EVERY_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [connected]);
  return status;
}

export function StationStages({ station }: { station: StationStatus & { connected: true } }) {
  const rows: [string, boolean, string][] = [
    ["Light on the deck's sensors", station.light_sensors > 0, `${station.light_sensors} of 4`],
    ["Base station's data read", station.calibrated.length > 0,
      station.calibrated.length ? `station ${station.calibrated.join(", ")}` : "none"],
    ["Sweeps decoded into angles", station.received.length > 0,
      station.received.length ? `station ${station.received.join(", ")}` : "no — set the channels (Set up, step 3)"],
    ["Base station's place stored", station.measured.length > 0,
      station.measured.length ? "yes" : "no — measure it"],
    ["In use by the drone", station.active.length > 0,
      station.active.length ? `station ${station.active.join(", ")}` : "no"],
    ["Position settled", station.ready,
      station.uncertainty_cm == null ? "—" : `within ${station.uncertainty_cm} cm (under 5 needed)`],
  ];
  return (
    <ul className="grid border border-[var(--border)] text-xs" aria-label="From the base station's light to a position">
      {rows.map(([label, ok, detail]) => (
        <li key={label} className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-3 py-1.5 last:border-b-0">
          <span>{label}</span>
          <StatusDot tone={ok ? "good" : "warning"}>{detail}</StatusDot>
        </li>
      ))}
    </ul>
  );
}
