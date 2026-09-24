/**
 * The drone's vitals, now and for the last minute.
 *
 * Two parts: the current reading of each vital at the top, and beneath it a
 * one-line-per-second tail — the shape of a log an operator can watch out of
 * the corner of an eye while flying.
 *
 * IT SUBSCRIBES TO NOTHING. Both halves are derived from the telemetry frame
 * and the history buffer App.tsx already keeps for the live charts. The stream
 * module's own docstring explains why that matters: a per-caller subscription
 * added radio traffic four times a second during a hover, at exactly the moment
 * the link matters most.
 *
 * The tail is 1 Hz, downsampled from the 10 Hz buffer. Ten lines a second is
 * not a log anyone can read, and the charts already hold the full rate.
 */

import { useLayoutEffect, useMemo, useRef } from "react";
import { HISTORY_S, type History } from "@/App";
import { formatNumber } from "@/lib/format";

/** One line per whole second of the buffer, newest last. */
function perSecond(history: History): History {
  const out: History = [];
  let lastSecond = Number.NaN;
  for (const frame of history) {
    const second = Math.floor(frame.t);
    if (second === lastSecond) continue;
    lastSecond = second;
    out.push(frame);
  }
  return out;
}

export function VitalsTail({ history }: { history: History }) {
  const tail = useMemo(() => perSecond(history), [history]);
  const box = useRef<HTMLDivElement>(null);

  // Always at the bottom. The buffer is a rolling 60 seconds, so lines leave
  // from the top — holding a scroll position inside it would drift anyway.
  useLayoutEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [tail]);

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="mono grid shrink-0 grid-cols-[3.6rem_1fr] gap-x-2 border-b border-[var(--console-line)] bg-[var(--console)] px-3 py-1 text-[10px] uppercase tracking-[0.06em] text-[var(--console-dim)]">
        <span>Elapsed</span>
        <span>z · vbat · roll · pitch · yaw · thrust · motors</span>
      </div>

      <div
        ref={box}
        role="log"
        aria-label="Vitals, one line per second"
        className="console console-scroll min-h-0 min-w-0 flex-1 overflow-auto px-3 py-1.5"
      >
        {tail.length === 0 ? (
          <p className="text-[var(--console-dim)]">
            No readings yet. They start arriving when the session connects to the drone.
          </p>
        ) : (
          <ol>
            {tail.map((frame) => (
              <li key={frame.t} className="flex gap-2 whitespace-nowrap">
                <span className="w-[3.4rem] shrink-0 text-right text-[var(--console-dim)]">
                  {frame.t.toFixed(1)}s
                </span>
                <span>
                  {pad(formatNumber(frame.height_m, 2), 6)}m
                  {"  "}
                  {pad(formatNumber(frame.values["pm.vbat"] ?? null, 2), 5)}V
                  {"  "}
                  {signed(frame.values["stabilizer.roll"])}
                  {" "}
                  {signed(frame.values["stabilizer.pitch"])}
                  {" "}
                  {signed(frame.values["stabilizer.yaw"])}
                  {"  "}
                  {pad(formatNumber(frame.values["stabilizer.thrust"] ?? null, 0), 6)}
                  {"  "}
                  <span className="text-[var(--console-dim)]">
                    [{[1, 2, 3, 4]
                      .map((m) => pad(formatNumber(frame.values[`motor.m${m}`] ?? null, 0), 5))
                      .join(" ")}]
                  </span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>

      <p className="mono border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">
        Last {HISTORY_S}s at one line per second · the same stream the guards and the CSV read
      </p>
    </div>
  );
}


/** Right-align inside a monospace column without a table. */
const pad = (text: string, width: number) => text.padStart(width, " ");

/** A signed 5-wide angle, so +1.2 and -11.4 keep the same column. */
const signed = (value: number | undefined) =>
  value == null ? pad("—", 6) : pad(`${value >= 0 ? "+" : ""}${value.toFixed(1)}`, 6);
