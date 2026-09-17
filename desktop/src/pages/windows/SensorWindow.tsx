/**
 * The live sensor windows.
 *
 * All five read the same 10 Hz stream the guards and the CSV read, so what the
 * operator sees is what the flight recorded — not a second, prettier version.
 *
 * Only variables this drone actually publishes appear with a value; anything
 * the firmware does not have says so rather than showing a confident zero. The
 * lab drone (checked 2026-09-16) publishes all of them.
 *
 * Positioning is the window that matters most after 2026-09-16: it shows
 * stations **received** next to stations with **valid geometry**, which is the
 * mismatch that let a drone fly blind into a wall.
 */

import type { ReactNode } from "react";
import type { History } from "@/App";
import { LiveChart, type Sample } from "@/pages/windows/LiveChart";
import type { Session, Telemetry } from "@/lib/agent";
import { Button, PageHeader, Panel, Stat, StatusDot } from "@/components/ui";

export type WindowKey = "flight" | "power" | "environment" | "motion" | "positioning";

/** A variable a window's log lists. `name` is the column in the session record. */
export type Variable = { name: string; label: string; unit?: string; digits?: number };

/**
 * What each window's detail log shows, per reading. The live window and its log
 * list the same things, so opening a chart never lands on a different story.
 */
export const WINDOW_VARIABLES: Record<WindowKey, Variable[]> = {
  flight: [
    { name: "height_m", label: "Height", unit: "m", digits: 2 },
    { name: "stateEstimate.x", label: "x", unit: "m", digits: 2 },
    { name: "stateEstimate.y", label: "y", unit: "m", digits: 2 },
    { name: "stabilizer.roll", label: "Roll", unit: "°", digits: 1 },
    { name: "stabilizer.pitch", label: "Pitch", unit: "°", digits: 1 },
    { name: "stabilizer.thrust", label: "Thrust", digits: 0 },
  ],
  power: [
    { name: "pm.vbat", label: "Battery", unit: "V", digits: 2 },
    { name: "sys.canfly", label: "Can fly", digits: 0 },
    { name: "motor.m1", label: "M1", digits: 0 },
    { name: "motor.m2", label: "M2", digits: 0 },
    { name: "motor.m3", label: "M3", digits: 0 },
    { name: "motor.m4", label: "M4", digits: 0 },
  ],
  environment: [
    { name: "baro.temp", label: "Temperature", unit: "°C", digits: 1 },
    { name: "baro.pressure", label: "Pressure", unit: "hPa", digits: 1 },
  ],
  motion: [
    { name: "acc.x", label: "Accel x", unit: "g", digits: 2 },
    { name: "acc.y", label: "Accel y", unit: "g", digits: 2 },
    { name: "acc.z", label: "Accel z", unit: "g", digits: 2 },
    { name: "gyro.x", label: "Gyro x", unit: "°/s", digits: 1 },
    { name: "gyro.y", label: "Gyro y", unit: "°/s", digits: 1 },
    { name: "gyro.z", label: "Gyro z", unit: "°/s", digits: 1 },
  ],
  positioning: [
    { name: "lighthouse.bsReceive", label: "Received (mask)", digits: 0 },
    { name: "lighthouse.bsGeoVal", label: "Geometry (mask)", digits: 0 },
    { name: "kalman.varPX", label: "Var x", unit: "m²", digits: 4 },
    { name: "kalman.varPY", label: "Var y", unit: "m²", digits: 4 },
  ],
};

export const WINDOWS: { key: WindowKey; label: string; note: string }[] = [
  { key: "flight", label: "Flight",
    note: "Where the drone is, how fast it is moving and how it is sitting in the air." },
  { key: "power", label: "Power",
    note: "The battery, what the firmware says about arming, and what each motor is doing." },
  { key: "environment", label: "Environment",
    note: "What the onboard sensors read of the room. These are the readings a mission records." },
  { key: "motion", label: "Motion",
    note: "Raw accelerometer and gyroscope, straight from the IMU." },
  { key: "positioning", label: "Positioning",
    note: "How well the drone can see where it is. The page to check before every flight." },
];

type WindowProps = { telemetry: Telemetry; history: History; onOpenLog: () => void };

/** A chart that opens this window's log when clicked, by pointer or keyboard. */
function ChartLink({ onOpen, children }: { onOpen: () => void; children: ReactNode }) {
  return (
    <div
      role="link"
      tabIndex={0}
      aria-label="Open the log of past sessions for this reading"
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter") onOpen();
      }}
      className="cursor-pointer rounded-md transition-opacity hover:opacity-80"
    >
      {children}
    </div>
  );
}

const value = (telemetry: Telemetry | null, name: string): number | null =>
  telemetry?.values[name] ?? null;

function series(history: History, pick: (frame: History[number]) => number | null): Sample[] {
  return history.map((frame) => ({ t: frame.t, value: pick(frame) }));
}

/** Base stations are a bitmask: bit n is station n. */
function stations(mask: number | null): number[] {
  if (mask === null) return [];
  return Array.from({ length: 16 }, (_, i) => i).filter((i) => (mask >> i) & 1);
}

export function SensorWindow({
  windowKey, telemetry, history, session, onOpenLog,
}: {
  windowKey: WindowKey;
  telemetry: Telemetry | null;
  history: History;
  session: Session | null;
  onOpenLog: () => void;
}) {
  const page = WINDOWS.find((w) => w.key === windowKey)!;
  const header = (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <PageHeader title={page.label}>{page.note}</PageHeader>
      <Button onClick={onOpenLog}>Past sessions log →</Button>
    </div>
  );

  if (session === null || session.state === "signed_out") {
    return (
      <div className="grid gap-5">
        {header}
        <Panel title="No readings">Sign in and start a session to see live readings.</Panel>
      </div>
    );
  }
  if (telemetry === null) {
    return (
      <div className="grid gap-5">
        {header}
        <Panel title="No readings">
          Nothing is arriving yet. Readings start when the session connects to the drone.
        </Panel>
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      {header}
      {windowKey === "flight" && <FlightWindow telemetry={telemetry} history={history} onOpenLog={onOpenLog} />}
      {windowKey === "power" && <PowerWindow telemetry={telemetry} history={history} onOpenLog={onOpenLog} />}
      {windowKey === "environment" && <EnvironmentWindow telemetry={telemetry} history={history} onOpenLog={onOpenLog} />}
      {windowKey === "motion" && <MotionWindow telemetry={telemetry} history={history} onOpenLog={onOpenLog} />}
      {windowKey === "positioning" && <PositioningWindow telemetry={telemetry} history={history} onOpenLog={onOpenLog} />}
    </div>
  );
}

function FlightWindow({ telemetry, history, onOpenLog }: WindowProps) {
  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Height above floor" value={telemetry.height_m} unit="m" />
        <Stat label="x" value={value(telemetry, "stateEstimate.x")} unit="m" digits={2} />
        <Stat label="y" value={value(telemetry, "stateEstimate.y")} unit="m" digits={2} />
        <Stat label="Thrust" value={value(telemetry, "stabilizer.thrust")} digits={0} />
      </section>
      <Panel title="Height above the floor (m)">
        <ChartLink onOpen={onOpenLog}>
          <LiveChart samples={series(history, (f) => f.height_m)} unit="m" />
        </ChartLink>
      </Panel>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Roll" value={value(telemetry, "stabilizer.roll")} unit="°" digits={1} />
        <Stat label="Pitch" value={value(telemetry, "stabilizer.pitch")} unit="°" digits={1} />
        <Stat label="Yaw" value={value(telemetry, "stabilizer.yaw")} unit="°" digits={1} />
      </section>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Speed x" value={value(telemetry, "stateEstimate.vx")} unit="m/s" />
        <Stat label="Speed y" value={value(telemetry, "stateEstimate.vy")} unit="m/s" />
        <Stat label="Speed up" value={value(telemetry, "stateEstimate.vz")} unit="m/s" />
      </section>
    </div>
  );
}

function PowerWindow({ telemetry, history, onOpenLog }: WindowProps) {
  const vbat = value(telemetry, "pm.vbat");
  const canfly = value(telemetry, "sys.canfly");
  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat
          label="Battery" value={vbat} unit="V"
          tone={vbat == null ? undefined : vbat < 3.3 ? "critical" : vbat < 3.75 ? "warning" : "good"}
          hint={vbat == null ? undefined
            : vbat < 3.75 ? "Below the arming threshold" : "Enough to arm"}
        />
        <Stat
          label="Will it arm?" value={canfly == null ? null : canfly ? "Yes" : "No"}
          hint="The drone's own verdict (sys.canfly)"
        />
        <Stat label="Power state" value={POWER_STATES[value(telemetry, "pm.state") ?? -1] ?? null} />
      </section>
      <Panel title="Battery (V)">
        <ChartLink onOpen={onOpenLog}>
          <LiveChart samples={series(history, (f) => f.values["pm.vbat"] ?? null)} unit="V" />
        </ChartLink>
      </Panel>
      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {[1, 2, 3, 4].map((motor) => (
          <Stat key={motor} label={`Motor ${motor}`}
                value={value(telemetry, `motor.m${motor}`)} digits={0} />
        ))}
      </section>
    </div>
  );
}

/** `pm.state` as the firmware defines it (pm.h: PMStates). */
const POWER_STATES: Record<number, string> = {
  0: "On battery", 1: "Charging", 2: "Charged", 3: "Low power", 4: "Shutting down",
};

function EnvironmentWindow({ telemetry, history, onOpenLog }: WindowProps) {
  return (
    <div className="grid gap-5">
      <section className="grid gap-4 sm:grid-cols-2">
        <Stat label="Temperature, raw sensor" value={value(telemetry, "baro.temp")} unit="°C"
              digits={1} hint="Reads warm: the drone heats its own sensor" />
        <Stat label="Pressure" value={value(telemetry, "baro.pressure")} unit="hPa" digits={1} />
      </section>
      <Panel
        title="Temperature (°C, raw)"
        note="The corrected value is computed for the flight record; this is what the sensor reports."
      >
        <ChartLink onOpen={onOpenLog}>
          <LiveChart samples={series(history, (f) => f.values["baro.temp"] ?? null)} unit="°C" />
        </ChartLink>
      </Panel>
      <Panel title="Pressure (hPa)">
        <ChartLink onOpen={onOpenLog}>
          <LiveChart samples={series(history, (f) => f.values["baro.pressure"] ?? null)} unit="hPa" />
        </ChartLink>
      </Panel>
    </div>
  );
}

function MotionWindow({ telemetry, history, onOpenLog }: WindowProps) {
  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Accel x" value={value(telemetry, "acc.x")} unit="g" />
        <Stat label="Accel y" value={value(telemetry, "acc.y")} unit="g" />
        <Stat label="Accel z" value={value(telemetry, "acc.z")} unit="g" />
      </section>
      <Panel title="Vertical acceleration (g)">
        <ChartLink onOpen={onOpenLog}>
          <LiveChart samples={series(history, (f) => f.values["acc.z"] ?? null)} unit="g" />
        </ChartLink>
      </Panel>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Gyro x" value={value(telemetry, "gyro.x")} unit="°/s" digits={1} />
        <Stat label="Gyro y" value={value(telemetry, "gyro.y")} unit="°/s" digits={1} />
        <Stat label="Gyro z" value={value(telemetry, "gyro.z")} unit="°/s" digits={1} />
      </section>
    </div>
  );
}

function PositioningWindow({ telemetry, history, onOpenLog }: WindowProps) {
  const received = stations(value(telemetry, "lighthouse.bsReceive"));
  const geometry = stations(value(telemetry, "lighthouse.bsGeoVal"));
  const calibrated = stations(value(telemetry, "lighthouse.bsCalVal"));
  const stored = stations(value(telemetry, "lighthouse.bsAvailable"));
  const usable = received.filter((s) => geometry.includes(s) && calibrated.includes(s));
  const varXY = Math.max(
    value(telemetry, "kalman.varPX") ?? 0, value(telemetry, "kalman.varPY") ?? 0,
  );

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat
          label="Base stations received" value={received.length ? received.join(", ") : "none"}
          tone={usable.length >= 2 ? "good" : "critical"}
          hint={usable.length >= 2 ? "Position is being measured" : "The drone cannot see where it is"}
        />
        <Stat label="With valid geometry" value={geometry.length ? geometry.join(", ") : "none"}
              hint={`Stored: ${stored.length ? stored.join(", ") : "none"}`} />
        <Stat
          label="Position uncertainty" value={varXY ? Math.sqrt(varXY) * 100 : null} unit="cm"
          digits={1}
          tone={varXY === 0 ? undefined : varXY < 0.0025 ? "good" : "warning"}
          hint={varXY < 0.0025 ? "Steady" : "Too uncertain to fly"}
        />
      </section>

      {received.length > 0 && usable.length < received.length && (
        <p role="status" className="rounded-lg border border-[var(--status-warning)] p-4 text-sm">
          <StatusDot tone="warning">
            Station(s) {received.filter((s) => !usable.includes(s)).join(", ")} are received but
            have no valid calibration or geometry for this room. Re-run geometry estimation in
            cfclient — flying on them is what sent a drone into the wall.
          </StatusDot>
        </p>
      )}

      <Panel
        title="Position uncertainty (cm)"
        note="How sure the drone is of where it is. It must stay small: 8.9 m of wander at rest is what a drone with no base station signal reports."
      >
        <ChartLink onOpen={onOpenLog}>
          <LiveChart
          samples={series(history, (f) => {
            const worst = Math.max(f.values["kalman.varPX"] ?? 0, f.values["kalman.varPY"] ?? 0);
            return worst ? Math.sqrt(worst) * 100 : null;
          })}
          unit="cm"
        />
        </ChartLink>
      </Panel>
    </div>
  );
}
