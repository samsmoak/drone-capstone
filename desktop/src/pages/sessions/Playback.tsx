/**
 * MISSION PLAYBACK — one recorded flight, watched again (Sessions › a session
 * › a flight › Play back).
 *
 * The room map (RoomMap: 2-D or 3-D, the same map Auto plans and flies on)
 * with the plan AS FLOWN, the path the drone actually flew drawn behind it
 * (trail.ts) and the drone where it was at the moment shown; under it Play /
 * Pause, ±1 s, the speed and a time slider marked with what happened; beside
 * it the readings at that moment — height, speed, drift, battery,
 * temperature, pressure, attitude, the loop's state and the keys held — the
 * events in words (each one a jump to its moment) and the mission report.
 * FULL SCREEN keeps all of it: the map large, the controls under it, the
 * readings and events beside it.
 *
 * RECORDED, NEVER SIMULATED (agent playback.py). Where the recording has a
 * gap — samples lost on the link — the drone is not drawn: nothing was
 * received, so nothing is shown. Where no base station was received the
 * drone is drawn where its own estimate put it, and the trail turns dashed
 * amber.
 *
 * NO KEYBOARD SHORTCUTS, ON PURPOSE. App.tsx's flight keys listen on the whole
 * window on every page: Space is swallowed (so it can never press a button
 * that stops the motors), L lands the drone, the arrows and W A S D fly it in
 * Manual. Playback reuses none of them — on-screen buttons, a <select> and the
 * native slider, whose own arrow keys never reach the flight handler (it
 * ignores keys typed into an input or a select).
 */

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  AgentError, api, type FlightPlayback, type PlaybackControl, type PlaybackEvent, type PlaybackSample,
} from "@/lib/agent";
import { formatDateTime, formatNumber } from "@/lib/format";
import { Button, Message, Panel, Spinner, Stat, StatusDot, type Tone } from "@/components/ui";
import { FullScreenOverlay } from "@/components/FullScreenOverlay";
import { RoomMap, type PointState } from "@/pages/control/auto/plan/RoomMap";
import { trailOf } from "@/pages/control/auto/plan/trail";
import type { Load } from "./parts";

const SPEEDS = [0.5, 1, 2, 4, 8] as const;
const STEP_S = 1;

/** The last row at or before `t` (rows sorted by t_s), or null before the first. */
export function rowAt<T extends { t_s: number }>(rows: T[], t: number): T | null {
  let lo = 0;
  let hi = rows.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t_s <= t) { found = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return found < 0 ? null : rows[found];
}

/** Inside a stretch with no samples (dropped on the link)? */
function inGap(gaps: FlightPlayback["gaps"], t: number): boolean {
  return gaps.some((g) => t > g.from_s && t < g.to_s);
}

/** Each inspection point's state at `t`: held already, being held, or ahead. */
function progressAt(samples: PlaybackSample[], t: number, ids: string[]): Record<string, PointState> {
  const seen = new Set<string>();
  let current: string | null = null;
  for (const s of samples) {
    if (s.t_s > t) break;
    if (s.point_id) seen.add(s.point_id);
    current = s.point_id;
  }
  return Object.fromEntries(ids.map((id) => [
    id, id === current ? "current" : seen.has(id) ? "done" : "pending",
  ]));
}

const EVENT_TONE: Record<PlaybackEvent["kind"], Tone> = {
  state: "idle", keys: "warning", hold: "good", position: "warning", gap: "critical",
};

const STATE_WORDS: Record<string, string> = {
  idle: "Disarmed", armed: "Armed", flying: "Flying", landing: "Landing", landed: "Landed",
  stopped: "Emergency stop",
};

function seconds(t: number): string {
  return `${t.toFixed(1)} s`;
}

export function FlightPlaybackView({
  flightId, title, onBack, backLabel = "← Back to the session", startAt = 0, startFullScreen = false,
}: {
  flightId: string;
  /** What the flight is called on the page it was opened from. */
  title: string;
  onBack: () => void;
  /** Where Back goes, in words. */
  backLabel?: string;
  /** The layout harness opens it mid-flight and full screen; the app does not. */
  startAt?: number;
  startFullScreen?: boolean;
}) {
  const [state, setState] = useState<Load<FlightPlayback>>({ kind: "loading" });
  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", data: await api.playback(flightId) });
    } catch (e) {
      setState({ kind: "error", message: e instanceof AgentError ? e.message : "Could not load this flight." });
    }
  }, [flightId]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="grid gap-4">
      <div>
        <button type="button" onClick={onBack} className="min-h-11 text-sm font-medium text-[var(--muted)] hover:text-[var(--foreground)]">
          {backLabel}
        </button>
      </div>
      {state.kind === "loading" && <Spinner label="Loading the flight's recording…" />}
      {state.kind === "error" && (
        <div className="grid gap-3">
          <Message tone="critical" text={state.message} />
          <div><Button onClick={() => void load()}>Try again</Button></div>
        </div>
      )}
      {state.kind === "ready" && <Player data={state.data} title={title} startAt={startAt} startFullScreen={startFullScreen} />}
    </div>
  );
}

function Player({ data, title, startAt, startFullScreen }: {
  data: FlightPlayback;
  title: string;
  startAt: number;
  startFullScreen: boolean;
}) {
  const end = data.duration_s;
  const [t, setT] = useState(() => Math.min(end, Math.max(0, startAt)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);
  const [full, setFull] = useState(startFullScreen);

  // The clock: requestAnimationFrame, advancing by real elapsed time × speed,
  // so playback keeps time whatever the frame rate. Stops at the end. The
  // time lives in a ref as well as state: the frame loop reads the ref, so
  // it never acts on a stale value between renders.
  const now = useRef(t);
  const last = useRef<number | null>(null);
  const seek = useCallback((next: number) => {
    const clamped = Math.min(end, Math.max(0, next));
    now.current = clamped;
    setT(clamped);
  }, [end]);
  useEffect(() => {
    if (!playing) { last.current = null; return; }
    let frame = 0;
    const tick = (at: number) => {
      const dt = last.current === null ? 0 : (at - last.current) / 1000;
      last.current = at;
      const next = now.current + dt * speed;
      if (next >= end) {
        seek(end);
        setPlaying(false);
        return;
      }
      seek(next);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, end, seek]);

  const play = () => {
    if (now.current >= end) seek(0);
    setPlaying(true);
  };

  const sample = rowAt(data.samples, t);
  const control = rowAt(data.control, t);
  const gap = inGap(data.gaps, t);
  const pointIds = useMemo(() => data.mission?.points.map((p) => p.id) ?? [], [data.mission]);
  const trail = useMemo(() => trailOf(data.samples, data.gaps, t), [data.samples, data.gaps, t]);
  const progress = useMemo(() => progressAt(data.samples, t, pointIds), [data.samples, t, pointIds]);

  const room = data.room;
  const shownDrone = !gap && sample && sample.x_m !== null && sample.y_m !== null
    ? [sample.x_m, sample.y_m] as [number, number] : null;
  const when = data.started_at ? formatDateTime(data.started_at) : "";
  const label = `${title}${when ? ` · ${when}` : ""}`;

  const map = (heightClass: string) => (
    <RoomMap
      outer={room?.outer ?? data.outer} fence={room?.geofence ?? null} obstacles={room?.obstacles ?? []}
      path={data.mission} takeoffHeight={data.mission?.cruise_height_m ?? 0.4}
      drone={shownDrone} droneHeight={shownDrone ? sample?.z_m ?? null : null}
      droneYaw={shownDrone ? sample?.yaw_deg ?? null : null}
      progress={data.mission ? progress : undefined} trail={trail} heightClass={heightClass}
      label={`Playback of ${label}: the plan as flown, the path flown, and the drone at ${seconds(t)}`}
    />
  );
  const controls = (
    <Controls t={t} end={end} playing={playing} speed={speed} data={data}
              onPlay={play} onPause={() => setPlaying(false)} onSeek={seek} onSpeed={setSpeed} />
  );
  const readings = <Readings sample={sample} control={control} gap={gap} unit={data.temp_unit} />;
  const events = (
    <Events events={data.events} t={t} onJump={(at) => { setPlaying(false); seek(at); }} />
  );

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">
            Playback · recorded, not simulated · {data.source === "supabase" ? "from Supabase" : "from this computer"}
          </p>
          <h2 className="wrap-anywhere text-lg font-bold text-[var(--heading)]">{label}</h2>
          <p className="text-xs">
            {data.mission ? `The plan as flown, ${data.mission.points.length} point${data.mission.points.length === 1 ? "" : "s"}` : "No plan kept"}
            {" · "}{seconds(end)} recorded · {data.samples.length} samples
          </p>
        </div>
        <Button onClick={() => setFull(true)}>Full screen</Button>
      </div>

      {data.notes.map((note) => <Message key={note} tone="warning" text={note} />)}

      <Legend />

      <div className="@container">
        <div className="grid gap-3 @3xl:grid-cols-[minmax(0,1.6fr)_minmax(16rem,1fr)]">
          {/* content-start: the readings column is taller, and a stretched row
              would stretch the map's own toolbar with it. */}
          <div className="grid min-w-0 content-start gap-2">
            {/* One map at a time: two WebGL views of one room is two GPU contexts. */}
            {full
              ? <div className="grid h-40 place-items-center border border-[var(--border)] text-sm">Showing full screen</div>
              : map("h-[clamp(18rem,52vh,34rem)]")}
            {!full && controls}
          </div>
          <div className="grid min-w-0 content-start gap-3">
            {!full && readings}
            {!full && events}
          </div>
        </div>
      </div>

      {data.report && <Report report={data.report} />}

      {full && (
        <FullScreenOverlay label={`Playback · ${label}`} onClose={() => setFull(false)}>
          {/* Side by side (lg) each column scrolls on its own, so they may
              shrink (min-h-0); stacked, the whole body scrolls and a row must
              never be shorter than its content — with min-h-0 there the
              readings slid up over the map at 720 px (measured 2026-10-11). */}
          <div className="grid min-h-0 flex-1 content-start gap-3 overflow-auto bg-[var(--background)] p-3 text-[var(--foreground)] lg:grid-cols-[minmax(0,1fr)_22rem] lg:overflow-hidden">
            <div className="grid min-w-0 content-start gap-2 lg:min-h-0">
              {map("h-[calc(100vh-21rem)] min-h-[18rem]")}
              {controls}
            </div>
            <div className="grid min-w-0 content-start gap-3 lg:min-h-0 lg:overflow-y-auto">
              {readings}
              {events}
            </div>
          </div>
        </FullScreenOverlay>
      )}
    </>
  );
}

/** How to read the map: said once, in words and the same marks. */
function Legend() {
  const swatch = (style: CSSProperties) => (
    <span aria-hidden="true" className="inline-block h-0 w-6 border-t-[3px]" style={style} />
  );
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs" aria-label="How to read the map">
      <li className="inline-flex items-center gap-2">{swatch({ borderColor: "var(--status-good)" })} Flown, position measured</li>
      <li className="inline-flex items-center gap-2">
        <span aria-hidden="true" className="inline-block bg-[var(--foreground)] py-px">
          {swatch({ borderColor: "var(--status-warning)", borderTopStyle: "dashed" })}
        </span>
        Flown with no base station (the drone's own estimate)
      </li>
      <li className="inline-flex items-center gap-2">{swatch({ borderColor: "var(--primary)", borderTopStyle: "dashed" })} The plan as flown</li>
    </ul>
  );
}

function Controls({ t, end, playing, speed, data, onPlay, onPause, onSeek, onSpeed }: {
  t: number;
  end: number;
  playing: boolean;
  speed: number;
  data: FlightPlayback;
  onPlay: () => void;
  onPause: () => void;
  onSeek: (t: number) => void;
  onSpeed: (s: number) => void;
}) {
  const pct = (s: number) => `${end > 0 ? (s / end) * 100 : 0}%`;
  return (
    <section aria-label="Playback controls" className="grid gap-2 border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        {playing
          ? <Button variant="primary" onClick={onPause}>Pause</Button>
          : <Button variant="primary" onClick={onPlay}>{t >= end ? "Play again" : "Play"}</Button>}
        <Button onClick={() => onSeek(0)} title="Back to the start of the recording">Start</Button>
        <Button onClick={() => onSeek(t - STEP_S)} title="One second back">−1 s</Button>
        <Button onClick={() => onSeek(t + STEP_S)} title="One second forward">+1 s</Button>
        <label className="ml-auto inline-flex items-center gap-2 text-sm">
          Speed
          <select value={speed} onChange={(e) => onSpeed(Number(e.target.value))}
                  className="min-h-11 border border-[var(--border)] bg-[var(--surface)] px-2 text-sm text-[var(--foreground)]">
            {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
          </select>
        </label>
      </div>

      <div className="grid gap-1">
        {/* What happened, marked along the time line. The events list is the
            readable version; these marks only show where to drag to. */}
        <div aria-hidden="true" className="relative h-3">
          {data.gaps.map((g) => (
            <span key={`g${g.from_s}`} className="absolute top-0 h-3"
                  style={{ left: pct(g.from_s), width: pct(g.to_s - g.from_s), background: "var(--status-critical)", minWidth: 2 }} />
          ))}
          {data.events.filter((e) => e.kind !== "gap").map((e, i) => (
            <span key={`e${i}`} className="absolute top-0 h-3 w-0.5"
                  style={{ left: pct(e.t_s), background: e.kind === "hold" ? "var(--status-good)" : e.kind === "state" ? "var(--foreground)" : "var(--status-warning)" }} />
          ))}
        </div>
        <input type="range" min={0} max={end} step={0.1} value={Math.min(t, end)}
               onChange={(e) => onSeek(Number(e.target.value))}
               aria-label="Time in the recording" aria-valuetext={`${t.toFixed(1)} of ${end.toFixed(1)} seconds`}
               className="w-full" />
        <p className="mono flex justify-between text-xs">
          <span>{seconds(t)}</span>
          <span>{seconds(end)}</span>
        </p>
      </div>
    </section>
  );
}

function Readings({ sample, control, gap, unit }: {
  sample: PlaybackSample | null;
  control: PlaybackControl | null;
  gap: boolean;
  unit: string | null;
}) {
  const tempUnit = unit === "F" ? "°F" : "°C";
  const status: ReactNode = gap
    ? <StatusDot tone="critical">No data — samples lost on the link</StatusDot>
    : !sample ? <StatusDot tone="idle">Before the first sample</StatusDot>
    : sample.positioned === false ? <StatusDot tone="warning">No base station — flying on its own estimate</StatusDot>
    : <StatusDot tone="good">Position measured</StatusDot>;
  return (
    <Panel title="At this moment" action={status} bodyClassName="grid gap-3 px-4 py-3">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="State" value={control ? STATE_WORDS[control.state] ?? control.state : null}
              hint={control?.keys ? `Keys held: ${control.keys}` : "No keys held"} />
        <Stat label="Holding at" value={sample?.point_id ?? "—"} />
        <Stat label="Height" value={sample?.z_m} unit="m" hint="Above the floor at takeoff" />
        <Stat label="Speed" value={sample?.speed_m_s} unit="m/s" hint={sample?.vz_m_s != null ? `Climbing ${formatNumber(sample.vz_m_s, 2)} m/s` : undefined} />
        <Stat label="Drift" value={control?.drift_m} unit="m" hint="From where it was sent" digits={3} />
        <Stat label="Height error" value={control?.height_error_m} unit="m" digits={3} hint="Off the height it held" />
        <Stat label="Battery" value={sample?.battery_v} unit="V" />
        <Stat label="Temperature" value={sample?.temp} unit={tempUnit} digits={1} />
        <Stat label="Pressure" value={sample?.pressure_hpa} unit="hPa" digits={1} />
        <Stat label="Heading" value={sample?.yaw_deg} unit="°" digits={0}
              hint={sample?.roll_deg != null && sample?.pitch_deg != null ? `Roll ${formatNumber(sample.roll_deg, 1)}°, pitch ${formatNumber(sample.pitch_deg, 1)}°` : undefined} />
      </div>
    </Panel>
  );
}

function Events({ events, t, onJump }: { events: PlaybackEvent[]; t: number; onJump: (t: number) => void }) {
  const current = rowAt(events, t);
  return (
    <Panel title="What happened" bodyClassName="px-2 py-2">
      {events.length === 0 ? (
        <p className="px-2 text-sm">Nothing to report: no state changes, holds, keys or lost samples were recorded.</p>
      ) : (
        <ol className="grid gap-0.5" aria-label="Events, each a jump to its moment">
          {events.map((e, i) => {
            const now = current === e;
            return (
              <li key={`${e.t_s}-${i}`}>
                <button type="button" onClick={() => onJump(e.t_s)} aria-current={now ? "true" : undefined}
                        className={`grid min-h-11 w-full grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2 px-2 text-left text-sm hover:bg-[var(--surface-2)] ${now ? "bg-[var(--surface-2)] font-semibold" : ""}`}>
                  <span className="mono text-xs">{seconds(e.t_s)}</span>
                  <StatusDot tone={EVENT_TONE[e.kind]}>{e.text}</StatusDot>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

function Report({ report }: { report: NonNullable<FlightPlayback["report"]> }) {
  const n = (v: number | null, unit: string, digits = 1) => (v === null ? "—" : `${v.toFixed(digits)} ${unit}`);
  return (
    <Panel title="The mission report" bodyClassName="grid gap-3 px-4 py-3">
      <p className="text-sm">
        Flown in {n(report.flown_s, "s")} against the planner's estimate of {n(report.estimate_s, "s")}
        {report.longer_than_estimate ? " — longer than planned." : "."}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <caption className="sr-only">Each inspection point: travel, settle, hold and drift</caption>
          <thead className="text-xs">
            <tr className="border-b border-[var(--border)]">
              <th scope="col" className="py-2 pr-3">Point</th>
              <th scope="col" className="py-2 pr-3">Travel (planned)</th>
              <th scope="col" className="py-2 pr-3">Settle</th>
              <th scope="col" className="py-2 pr-3">Held (asked)</th>
              <th scope="col" className="py-2 pr-3">Drift, median / worst</th>
              <th scope="col" className="py-2">Notes</th>
            </tr>
          </thead>
          <tbody>
            {report.legs.map((leg) => (
              <tr key={leg.to} className="border-b border-[var(--border)] align-top">
                <th scope="row" className="mono py-2 pr-3">{leg.to === "start" ? "Back over the start" : leg.to}{leg.label ? ` · ${leg.label}` : ""}</th>
                <td className="py-2 pr-3">{leg.reached ? `${n(leg.transit_s, "s")} (${n(leg.planned_s, "s")})` : "Not reached"}</td>
                <td className="py-2 pr-3">{n(leg.settle_s, "s")}</td>
                <td className="py-2 pr-3">
                  {leg.hold_s === null ? "—" : `${n(leg.hold_s, "s")} (${n(leg.hold_required_s, "s")})`}
                  {leg.hold_long_enough === false && <span className="block"><StatusDot tone="warning">Short</StatusDot></span>}
                </td>
                <td className="py-2 pr-3">{leg.hold_drift_median_m === null ? "—" : `${n(leg.hold_drift_median_m * 100, "cm")} / ${n((leg.hold_drift_worst_m ?? 0) * 100, "cm")}`}</td>
                <td className="py-2 text-xs">{leg.notes.join(" ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {report.notes.map((note) => <p key={note} className="text-xs">{note}</p>)}
    </Panel>
  );
}
