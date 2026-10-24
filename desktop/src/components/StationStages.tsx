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
import { api, type PositionBlocker, type StationRow, type StationStatus } from "@/lib/agent";
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
  const deck = station.deck;
  const rows: [string, boolean, string][] = [
    // The deck itself first (2026-10-24): a deck not detected, or not running
    // its firmware, reads exactly like stations that are off — 0 of 4.
    ...(deck ? [
      ["Positioning deck detected", deck.detected !== false,
       deck.detected === null ? "not known" : deck.detected ? "yes" : "no — switch the drone off and on"],
      ["Deck firmware running", deck.needs_fw !== true,
       deck.needs_fw === null ? "not asked yet" : deck.needs_fw ? "no — reinstall it (Set up, step 2)" : "yes"],
    ] as [string, boolean, string][] : []),
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
    <div className="grid gap-2">
      {station.blocker && <BlockerNote blocker={station.blocker} />}
      <ul className="grid border border-[var(--border)] text-xs" aria-label="From the base station's light to a position">
        {rows.map(([label, ok, detail]) => (
          <li key={label} className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-3 py-1.5 last:border-b-0">
            <span>{label}</span>
            <StatusDot tone={ok ? "good" : "warning"}>{detail}</StatusDot>
          </li>
        ))}
      </ul>
      {station.stations && <PerStation rows={station.stations} />}
    </div>
  );
}

/** The first stage that is not done, and what fixes it — said once, above
 *  the rows, so the operator does not have to find it in the list. */
export function BlockerNote({ blocker }: { blocker: PositionBlocker }) {
  return (
    <div role="status" className="grid gap-1 border-l-2 border-[var(--status-warning)] bg-[var(--surface-2)] px-3 py-2 text-sm">
      <p className="font-semibold">{blocker.text}</p>
      <p className="text-xs">{blocker.fix}</p>
    </div>
  );
}

/**
 * The chain per station, by channel — so with two stations it is plain which
 * one is seen, measured and in use (2026-10-24, the lab's second station).
 * The drone cannot see a second station on the SAME channel — the two blur
 * into one — so one row while two are on is said, with the fix.
 */
function PerStation({ rows }: { rows: StationRow[] }) {
  if (rows.length === 0) return null;
  const mark = (ok: boolean) => (ok ? "✓" : "—");
  return (
    <div className="grid gap-1.5">
      <div className="overflow-x-auto border border-[var(--border)]">
        <table className="w-full min-w-[22rem] text-xs">
          <caption className="sr-only">Each base station, by channel</caption>
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-[var(--muted)]">
              <th scope="col" className="px-3 py-1.5 font-medium">Station</th>
              <th scope="col" className="px-2 py-1.5 font-medium">Data read</th>
              <th scope="col" className="px-2 py-1.5 font-medium">Sweeps</th>
              <th scope="col" className="px-2 py-1.5 font-medium">Place stored</th>
              <th scope="col" className="px-2 py-1.5 font-medium">In use</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-[var(--border)] last:border-b-0">
                <th scope="row" className="mono px-3 py-1.5 text-left font-semibold">Ch {r.channel}</th>
                <td className="mono px-2 py-1.5" aria-label={r.calibrated ? "yes" : "no"}>{mark(r.calibrated)}</td>
                <td className="mono px-2 py-1.5" aria-label={r.received ? "yes" : "no"}>{mark(r.received)}</td>
                <td className="mono px-2 py-1.5" aria-label={r.measured ? "yes" : "no"}>{mark(r.measured)}</td>
                <td className="mono px-2 py-1.5" aria-label={r.active ? "yes" : "no"}>{mark(r.active)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 1 && (
        <p className="text-xs text-[var(--muted)]">
          One station is seen. If two are on, they must be on different channels — 1 and 2 (Set up,
          step 3) — or the drone sees them as one.
        </p>
      )}
      {rows.some((r) => r.received && !r.measured) && (
        <p className="text-xs">
          A station is received but its place is not stored: measure with the drone where every station can see it.
        </p>
      )}
    </div>
  );
}
