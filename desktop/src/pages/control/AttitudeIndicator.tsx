/**
 * How the drone is sitting in the air — the instrument cfclient calls an ADI.
 *
 * The horizon rotates against the aircraft, the pitch ladder slides, and a
 * sky pointer reads the bank angle off a fixed scale. Beneath it, a compass
 * strip for yaw and the raw gyro rates.
 *
 * WHERE THE DATA COMES FROM: `stabilizer.roll`, `stabilizer.pitch`,
 * `stabilizer.yaw` and `gyro.x/y/z` — all of them already arriving at 10 Hz in
 * the one shared subscription (backend/agent/cropwatcher/telemetry/stream.py).
 * Nothing new is subscribed and no extra radio traffic is generated: the
 * stream's own docstring explains why that matters during a hover.
 *
 * 10 Hz is a tenth of cfclient's rate, so the needle steps rather than glides.
 * A short CSS transition smooths the picture; the STREAM RATE IS NOT TOUCHED,
 * because the guards and the CSV read the same subscription.
 *
 * A missing reading says so. A level horizon drawn from no data would tell an
 * operator the drone is sitting flat when nothing at all is known.
 */

import type { Telemetry } from "@/lib/agent";
import { formatNumber } from "@/lib/format";

/** Screen units per degree of pitch. ±40° fits the 80-unit half-height. */
const PPD = 2;

/** Bank ticks on the fixed outer scale, in degrees either side of level. */
const BANK_TICKS = [0, 10, 20, 30, 45, 60];

/** Pitch ladder: labelled every 10°, a short mark every 5°. */
const PITCH_MAJOR = [-30, -20, -10, 10, 20, 30];
const PITCH_MINOR = [-25, -15, -5, 5, 15, 25];

const read = (telemetry: Telemetry | null, name: string): number | null =>
  telemetry?.values[name] ?? null;

export function AttitudeIndicator({ telemetry }: { telemetry: Telemetry | null }) {
  const roll = read(telemetry, "stabilizer.roll");
  const pitch = read(telemetry, "stabilizer.pitch");
  const yaw = read(telemetry, "stabilizer.yaw");
  const known = roll !== null && pitch !== null;

  // Clamped only for DRAWING. The numbers printed below are the real ones, so a
  // drone past 40° of pitch still reports what it actually did.
  const drawRoll = roll ?? 0;
  const drawPitch = Math.max(-40, Math.min(40, pitch ?? 0));

  return (
    <div className="grid gap-3 p-4">
      <div className="flex flex-wrap items-start gap-4">
        <svg
          viewBox="0 0 200 200"
          className="h-[180px] w-[180px] shrink-0"
          role="img"
          aria-label={
            known
              ? `Attitude: roll ${formatNumber(roll, 1)} degrees, pitch ${formatNumber(pitch, 1)} degrees`
              : "Attitude: no reading"
          }
        >
          <defs>
            <clipPath id="adi-face">
              <circle cx="100" cy="100" r="82" />
            </clipPath>
          </defs>

          {/* The moving world, clipped to the instrument face. */}
          <g clipPath="url(#adi-face)">
            <g
              style={{
                transform: `rotate(${-drawRoll}deg) translateY(${drawPitch * PPD}px)`,
                transformOrigin: "100px 100px",
                transition: "transform 90ms linear",
              }}
            >
              {/* Oversized so a rotated, translated world never shows a corner. */}
              <rect x="-150" y="-250" width="500" height="350" fill="var(--adi-sky)" />
              <rect x="-150" y="100" width="500" height="350" fill="var(--adi-ground)" />
              <line x1="-150" y1="100" x2="350" y2="100" stroke="var(--adi-ink)" strokeWidth="1.5" />

              {PITCH_MINOR.map((deg) => (
                <line
                  key={deg}
                  x1="90" x2="110"
                  y1={100 - deg * PPD} y2={100 - deg * PPD}
                  stroke="var(--adi-ink)" strokeWidth="1" opacity="0.85"
                />
              ))}
              {PITCH_MAJOR.map((deg) => (
                <g key={deg}>
                  <line
                    x1="78" x2="122"
                    y1={100 - deg * PPD} y2={100 - deg * PPD}
                    stroke="var(--adi-ink)" strokeWidth="1.2"
                  />
                  {/* Labels are TEXT: 5.17:1 on the sky, 7.94:1 on the ground. */}
                  <text
                    x="72" y={100 - deg * PPD + 3}
                    textAnchor="end" fontSize="9" fill="var(--adi-ink)"
                    className="mono"
                  >
                    {Math.abs(deg)}
                  </text>
                </g>
              ))}
            </g>

            {/* The sky pointer rides the roll but not the pitch, so it reads
                bank angle off the fixed scale below. */}
            <g
              style={{
                transform: `rotate(${-drawRoll}deg)`,
                transformOrigin: "100px 100px",
                transition: "transform 90ms linear",
              }}
            >
              <path d="M100 22 L95 32 L105 32 Z" fill="var(--adi-ink)" />
            </g>
          </g>

          {/* The fixed bank scale, outside the face. */}
          {BANK_TICKS.flatMap((deg) => (deg === 0 ? [0] : [deg, -deg])).map((deg) => {
            const a = ((deg - 90) * Math.PI) / 180;
            const long = deg === 0 || Math.abs(deg) === 30 || Math.abs(deg) === 60;
            const r1 = 82;
            const r2 = 82 + (long ? 9 : 5);
            return (
              <line
                key={deg}
                x1={100 + r1 * Math.cos(a)} y1={100 + r1 * Math.sin(a)}
                x2={100 + r2 * Math.cos(a)} y2={100 + r2 * Math.sin(a)}
                stroke="var(--border)" strokeWidth={long ? 2 : 1.2}
              />
            );
          })}
          <circle cx="100" cy="100" r="82" fill="none" stroke="var(--border)" strokeWidth="1.5" />

          {/* The aircraft reference: fixed to the instrument, never moves. */}
          <g stroke="var(--status-warning)" strokeWidth="2.5" fill="none">
            <path d="M58 100 L84 100" />
            <path d="M116 100 L142 100" />
            <path d="M94 100 L100 107 L106 100" />
          </g>

          {!known && (
            <>
              <circle cx="100" cy="100" r="82" fill="var(--surface)" opacity="0.88" />
              <text
                x="100" y="104" textAnchor="middle" fontSize="11"
                fill="var(--muted)" className="mono"
              >
                NO ATTITUDE DATA
              </text>
            </>
          )}
        </svg>

        <dl className="mono grid min-w-0 flex-1 grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <Readout label="Roll" value={roll} unit="°" digits={1} />
          <Readout label="Pitch" value={pitch} unit="°" digits={1} />
          <Readout label="Yaw" value={yaw} unit="°" digits={1} />
          <Readout label="Thrust" value={read(telemetry, "stabilizer.thrust")} unit="" digits={0} />
          <Readout label="Gyro x" value={read(telemetry, "gyro.x")} unit="°/s" digits={1} />
          <Readout label="Gyro y" value={read(telemetry, "gyro.y")} unit="°/s" digits={1} />
          <Readout label="Gyro z" value={read(telemetry, "gyro.z")} unit="°/s" digits={1} />
          <Readout label="Height" value={telemetry?.height_m ?? null} unit="m" digits={2} />
        </dl>
      </div>

      <Compass yaw={yaw} />
    </div>
  );
}

function Readout({ label, value, unit, digits }: {
  label: string;
  value: number | null;
  unit: string;
  digits: number;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-[var(--muted)]">{label}</dt>
      {/* The figure is never muted — grey is for the label. A missing reading
          shows an em dash, not a confident zero. */}
      <dd className={value === null ? "text-[var(--muted)]" : "font-semibold"}>
        {value === null ? "—" : `${formatNumber(value, digits)}${unit && ` ${unit}`}`}
      </dd>
    </div>
  );
}

/** Yaw as a sliding heading strip: 90° of arc either side of where it points. */
const COMPASS_SPAN = 90;
const COMPASS_W = 260;
const CARDINALS: Record<number, string> = { 0: "N", 90: "E", 180: "S", 270: "W" };

function Compass({ yaw }: { yaw: number | null }) {
  if (yaw === null) {
    return (
      <p className="mono border border-[var(--border)] px-3 py-2 text-center text-[11px] text-[var(--muted)]">
        NO HEADING DATA
      </p>
    );
  }
  // stabilizer.yaw arrives as -180..180; a compass reads 0..360.
  const heading = ((yaw % 360) + 360) % 360;
  const perDeg = COMPASS_W / (COMPASS_SPAN * 2);

  // Every 15°, across the visible window plus a margin so a mark never pops in.
  const marks: number[] = [];
  const first = Math.floor((heading - COMPASS_SPAN - 15) / 15) * 15;
  for (let d = first; d <= heading + COMPASS_SPAN + 15; d += 15) marks.push(d);

  return (
    <div className="relative overflow-hidden border border-[var(--border)] bg-[var(--surface-2)]">
      <svg viewBox={`0 0 ${COMPASS_W} 34`} className="block w-full" role="img"
           aria-label={`Heading ${formatNumber(heading, 0)} degrees`}>
        {marks.map((deg) => {
          const x = COMPASS_W / 2 + (deg - heading) * perDeg;
          const normalised = ((deg % 360) + 360) % 360;
          const cardinal = CARDINALS[normalised];
          const major = normalised % 45 === 0;
          return (
            <g key={deg}>
              <line
                x1={x} y1={0} x2={x} y2={major ? 10 : 6}
                stroke="var(--axis)" strokeWidth={major ? 1.6 : 1}
              />
              {major && (
                <text
                  x={x} y={24} textAnchor="middle" fontSize="11"
                  className="mono"
                  fill={cardinal ? "var(--foreground)" : "var(--muted)"}
                  fontWeight={cardinal ? 700 : 400}
                >
                  {cardinal ?? normalised}
                </text>
              )}
            </g>
          );
        })}
        {/* The index: where the drone is actually pointing. */}
        <path
          d={`M${COMPASS_W / 2} 12 L${COMPASS_W / 2 - 5} 2 L${COMPASS_W / 2 + 5} 2 Z`}
          fill="var(--primary)"
        />
      </svg>
    </div>
  );
}
