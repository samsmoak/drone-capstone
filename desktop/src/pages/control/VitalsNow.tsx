/**
 * The six numbers worth glancing at while flying.
 *
 * IT LIVES IN THE STRIP AT THE TOP, not in the console, and that is the point:
 * inside the Vitals tab these disappeared the moment the operator looked at the
 * camera or the scene. A battery reading that hides behind a tab is not a
 * battery reading. Up here they are on screen whatever the console is showing,
 * beside the keys they belong with.
 *
 * Moving them out also gave the command log its height back — it was sharing
 * the console with this grid, the tail and the attitude indicator.
 *
 * The rules come from ui.tsx unchanged: the label is muted, THE FIGURE NEVER
 * IS, a missing value says so rather than rendering blank or zero, and a tone
 * ships as icon + words.
 */

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

export function VitalsNow({ telemetry, session }: {
  telemetry: Telemetry | null;
  session: Session | null;
}) {
  const vbat = read(telemetry, "pm.vbat") ?? session?.drone?.battery_v ?? null;
  const varCm = telemetry ? uncertaintyCm(telemetry.values) : null;
  const canfly = read(telemetry, "sys.canfly");

  return (
    <div className="mono grid shrink-0 grid-cols-3 gap-x-5 gap-y-2 text-xs">
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
