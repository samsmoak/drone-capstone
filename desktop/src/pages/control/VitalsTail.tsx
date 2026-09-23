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
import type { Session, Telemetry } from "@/lib/agent";
import { formatNumber } from "@/lib/format";
import { StatusDot, type Tone } from "@/components/ui";

const read = (telemetry: Telemetry | null, name: string): number | null =>
  telemetry?.values[name] ?? null;

/** Position uncertainty in cm — the worst of the two horizontal variances. */
function uncertaintyCm(values: Record<string, number>): number | null {
  const worst = Math.max(values["kalman.varPX"] ?? 0, values["kalman.varPY"] ?? 0);
  return worst ? Math.sqrt(worst) * 100 : null;
}

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

export function VitalsTail({ telemetry, history, session }: {
  telemetry: Telemetry | null;
  history: History;
  session: Session | null;
}) {
  const tail = useMemo(() => perSecond(history), [history]);
  const box = useRef<HTMLDivElement>(null);

  // Always at the bottom. The buffer is a rolling 60 seconds, so lines leave
  // from the top — holding a scroll position inside it would drift anyway.
  useLayoutEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [tail]);

  const vbat = read(telemetry, "pm.vbat") ?? session?.drone?.battery_v ?? null;
  const varCm = telemetry ? uncertaintyCm(telemetry.values) : null;
  const canfly = read(telemetry, "sys.canfly");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Now. Six figures, each with the unit and a tone where one applies. */}
      <div className="mono grid grid-cols-3 gap-x-4 gap-y-2 border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-2.5 text-xs">
        <Vital
          label="Battery" value={vbat} unit="V" digits={2}
          tone={vbat == null ? undefined : vbat < 3.3 ? "critical" : vbat < 3.75 ? "warning" : "good"}
        />
        <Vital label="Height" value={telemetry?.height_m ?? null} unit="m" digits={2} />
        <Vital
          label="Uncertainty" value={varCm} unit="cm" digits={1}
          tone={varCm == null ? undefined : varCm < 5 ? "good" : "warning"}
        />
        <Vital label="Thrust" value={read(telemetry, "stabilizer.thrust")} unit="" digits={0} />
        <Vital label="Temp, raw" value={read(telemetry, "baro.temp")} unit="°C" digits={1} />
        {/* The drone's own verdict, never a voltage threshold guessed here. */}
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.08em] text-[var(--muted)]">Will it arm</p>
          <p className="mt-0.5 font-semibold">
            {canfly == null ? (
              <span className="text-[var(--muted)]">—</span>
            ) : (
              <StatusDot tone={canfly ? "good" : "critical"}>{canfly ? "Yes" : "No"}</StatusDot>
            )}
          </p>
        </div>
      </div>

      <div className="mono grid grid-cols-[3.6rem_1fr] gap-x-2 border-b border-[var(--console-line)] bg-[var(--console)] px-3 py-1 text-[10px] uppercase tracking-[0.06em] text-[var(--console-dim)]">
        <span>Elapsed</span>
        <span>z · vbat · roll · pitch · yaw · thrust · motors</span>
      </div>

      <div
        ref={box}
        role="log"
        aria-label="Vitals, one line per second"
        className="console console-scroll min-h-0 flex-1 overflow-y-auto px-3 py-1.5"
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

function Vital({ label, value, unit, digits, tone }: {
  label: string;
  value: number | null;
  unit: string;
  digits: number;
  tone?: Tone;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-[0.08em] text-[var(--muted)]">{label}</p>
      {/* The label is muted; the figure never is. */}
      <p className="mt-0.5 font-semibold">
        {value === null ? (
          <span className="text-[var(--muted)]">—</span>
        ) : tone ? (
          <StatusDot tone={tone}>{`${formatNumber(value, digits)}${unit && ` ${unit}`}`}</StatusDot>
        ) : (
          `${formatNumber(value, digits)}${unit && ` ${unit}`}`
        )}
      </p>
    </div>
  );
}

/** Right-align inside a monospace column without a table. */
const pad = (text: string, width: number) => text.padStart(width, " ");

/** A signed 5-wide angle, so +1.2 and -11.4 keep the same column. */
const signed = (value: number | undefined) =>
  value == null ? pad("—", 6) : pad(`${value >= 0 ? "+" : ""}${value.toFixed(1)}`, 6);
