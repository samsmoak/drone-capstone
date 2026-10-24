/**
 * Manual's room — drawn on the spot from the two base stations, with the drone
 * in it and the arrow keys round it (2026-10-24, Samuel: "we first detect the
 * two base stations, then we draw that room on the spot, and we show the
 * drone's position in that particular room … and forward, backwards, left and
 * right on the drone, so the user can see that before they press Start, and
 * as they are flying").
 *
 * THE SAME MAP AS AUTO'S MISSION PLANNER (auto/plan/RoomMap.tsx): 2-D or 3-D,
 * the tripods with their channels, the origin and Forward, the green space.
 * Nothing is drawn by hand — no room, no path, no points:
 *
 *   the room    where the measured stations' light reaches, over the agent's
 *               flying area (agent GET /station/space — the same prediction
 *               as Auto's ③ green, without a room)
 *   the drone   live, 2.5× its Auto size, its trail since the window opened
 *   the keys    F / B / L / R round it: where ↑ ↓ ← → move it NOW, which is
 *               never along the nose (keyArrows.ts, lib/keyDirections.ts);
 *               the nose is its own red tick
 *
 * Shown, not enforced: the green is where the position can be trusted, not a
 * fence the guard holds the drone inside (the guard's area is the square).
 *
 * Without a position — the stations not heard — the drone cannot be placed,
 * so a compass takes its place: ↑ at the top, the nose turning with the drone.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { History, Run } from "@/App";
import { AgentError, api, type OuterBound, type Session, type StationSpace, type Telemetry, type XY } from "@/lib/agent";
import { FullScreenOverlay } from "@/components/FullScreenOverlay";
import { StationStages, useStation } from "@/components/StationStages";
import { Button, Message, Spinner, type Tone } from "@/components/ui";
import { keyForward, FRAME_WORDS, type KeyForward } from "@/lib/keyDirections";
import { channelOf, useStationsHeard } from "@/lib/stationsHeard";
import { dronePosition } from "./auto/plan/MissionStep";
import { RoomMap } from "./auto/plan/RoomMap";
import { SmallButton } from "./auto/plan/fields";
import { KEY_DIRECTIONS } from "./auto/plan/keyArrows";
import type { SpaceLayer } from "./auto/plan/space";
import type { Trail, TrailRun } from "./auto/plan/trail";

/** The drone, drawn this much larger than Auto's: it is the thing being flown. */
const MANUAL_DRONE_SCALE = 2.5;
/** How often the room is asked for. The agent keeps it until the stations are
 *  measured again, so asking is cheap; a measurement shows within this. */
const SPACE_EVERY_MS = 3000;
/** Trail points kept: about a minute at the stream's 10 Hz. */
const TRAIL_POINTS = 600;
/** A Kalman variance this tight is a measured position (flight_guard's 10 cm). */
const MEASURED_VAR_M2 = 0.01;

type Loaded = { state: "loading" } | { state: "failed"; message: string } | { state: "ready"; space: StationSpace };

function useStationSpace(connected: boolean): [Loaded, () => void] {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!connected) return;
    let live = true;
    const ask = () => api.stationSpace()
      .then((space) => { if (live) setLoaded({ state: "ready", space }); })
      .catch((e: unknown) => {
        if (live) setLoaded({ state: "failed", message: e instanceof AgentError ? e.message : "The flight agent did not answer." });
      });
    void ask();
    const timer = window.setInterval(() => void ask(), SPACE_EVERY_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [connected, attempt]);
  return [loaded, () => { setLoaded({ state: "loading" }); setAttempt((n) => n + 1); }];
}

/** The predicted reach as the map's green (space.ts), at every height. */
function layerOf(space: StationSpace): SpaceLayer | null {
  const ever = space.predicted?.everywhere;
  return ever
    ? { kind: "predicted", vertices: ever.vertices, z_min: ever.z_min, z_max: ever.z_max, slices: space.predicted?.slices }
    : null;
}

/** The agent's flying area — the guard's square — as the map's outer bound. */
function squareOf(half: number): OuterBound {
  return { vertices: [[-half, -half], [half, -half], [half, half], [-half, half]], measured: false };
}

/** Where the drone has been since the window opened, in runs: green where
 *  its position was measured, dashed amber where it was only estimated. */
function liveTrail(history: History): Trail {
  const runs: Trail = [];
  let run: TrailRun | null = null;
  for (const h of history.slice(-TRAIL_POINTS)) {
    const x = h.values["stateEstimate.x"];
    const y = h.values["stateEstimate.y"];
    if (x === undefined || y === undefined || h.height_m === null) { run = null; continue; }
    const varXY = Math.max(h.values["kalman.varPX"] ?? 1, h.values["kalman.varPY"] ?? 1);
    const measured = varXY < MEASURED_VAR_M2 && (h.values["lighthouse.bsGeoVal"] ?? 0) > 0;
    if (!measured && !run) continue;                 // nothing to attach an estimate to
    if (!run || run.measured !== measured) {
      const next: TrailRun = { points: run?.points.length ? [run.points[run.points.length - 1]] : [], measured };
      run = next;
      runs.push(next);
    }
    run.points.push([x, y, Math.max(0, h.height_m)]);
  }
  return runs.filter((r) => r.points.length > 1);
}

export function ManualMap({ session, telemetry, history, run }: {
  session: Session;
  telemetry: Telemetry | null;
  history: History;
  run: Run;
}) {
  const [full, setFull] = useState(false);
  const fullButton = (
    <SmallButton onClick={() => setFull(true)} title="Show the room full screen — fly from it">Full screen ⤢</SmallButton>
  );
  return (
    <>
      <ManualMapBody session={session} telemetry={telemetry} history={history} run={run}
                     fill toolbar={fullButton} />
      {full && (
        <FullScreenOverlay label="Room — manual flight" onClose={() => setFull(false)}>
          <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-[var(--surface)] p-3">
            <ManualMapBody session={session} telemetry={telemetry} history={history} run={run} fill />
          </div>
        </FullScreenOverlay>
      )}
    </>
  );
}

function ManualMapBody({ session, telemetry, history, run, fill = false, toolbar }: {
  session: Session;
  telemetry: Telemetry | null;
  history: History;
  run: Run;
  /** Fill the parent's height (a flex column) — the console pane, or full screen. */
  fill?: boolean;
  toolbar?: ReactNode;
}) {
  const connected = session.radio?.state === "connected";
  const [loaded, retry] = useStationSpace(connected);
  const heard = useStationsHeard(telemetry);
  const live = dronePosition(telemetry);
  // NEVER DROP THE DRONE (2026-10-24, Samuel: "once the drone begins to fly it
  // goes out of the editor"). Losing the stations in the air took it off the
  // map. Now it stays where it was last placed, in the warning colour, and
  // the page says the position is lost. Forgotten when the radio drops.
  const last = useRef<XY | null>(null);
  useEffect(() => {
    if (live) last.current = live;
    else if (!connected) last.current = null;
  });
  const drone = live ?? last.current;
  const lost = live === null && drone !== null;
  const yaw = telemetry?.values["stabilizer.yaw"] ?? null;

  // keyframe.py's hysteresis, remembered between frames.
  const near = useRef(false);
  const forward: KeyForward = keyForward(session.controls, drone, yaw, near.current);
  useEffect(() => { near.current = forward.near; }, [forward.near]);

  const trail = useMemo(() => liveTrail(history), [history]);

  if (!connected) {
    return <Message tone="idle" text="Connect the drone to see the room: plug in the Crazyradio and switch the drone on." />;
  }
  if (loaded.state === "loading") return <Spinner label="Looking for the base stations…" />;
  if (loaded.state === "failed") {
    return (
      <div className="grid gap-2 p-3">
        <Message tone="critical" text={`Could not draw the room: ${loaded.message}`} />
        <div><Button onClick={retry}>Try again</Button></div>
      </div>
    );
  }
  const space = loaded.space;
  if (space.predicted === null) {
    return <NotMeasured session={session} run={run} drone={live} yaw={yaw} forward={forward} />;
  }

  const layer = layerOf(space);
  const placed = live !== null;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <RoomMap
        outer={squareOf(space.fence_half_extent_m)} fence={null} obstacles={[]} path={null}
        drone={drone} droneHeight={telemetry?.height_m ?? null} droneYaw={yaw} droneLost={lost}
        space={layer} trail={trail}
        keyArrows={placed && forward.deg !== null ? { forwardDeg: forward.deg } : null}
        droneScale={MANUAL_DRONE_SCALE} fill={fill} toolbar={toolbar}
        label="The room the base stations reach, the drone in it, and where each arrow key moves it"
      />
      {!layer && (
        <Message tone="warning" text="The base stations are measured, but their light does not overlap anywhere in the flying area — no green to draw." />
      )}
      <KeysLegend forward={forward} placed={placed} />
      {lost && (
        <Message tone="warning" text={`Position lost — ${heard && heard.heard.length ? `only ${heard.heard.map(channelOf).join(" and ")} heard, not enough to place it` : "no base station is heard"}. The drone is drawn where it was last placed (dashed). Until the stations are heard again, ↑ is the way the nose pointed at takeoff — see the compass.`} />
      )}
      {!placed && (
        <div className="grid gap-2">
          {!lost && <Message tone="warning" text={
            heard && heard.known.length
              ? `The drone is not placed in the room: it hears ${heard.heard.length ? heard.heard.map(channelOf).join(" and ") : "no base station"} — ${heard.heard.length ? "its position is not settled yet" : "check the stations are on and can see the top of the drone"}. Without a position Manual flies on the barometer.`
              : "The drone is not placed in the room: no base station is heard. Without a position Manual flies on the barometer."
          } />}
          {yaw !== null && forward.deg !== null && <Compass yaw={yaw} forwardDeg={forward.deg} />}
        </div>
      )}
    </div>
  );
}

/** What ↑ means now, and how to read the drawing. */
function KeysLegend({ forward, placed }: { forward: KeyForward; placed: boolean }) {
  if (!placed || forward.frame === null) return null;
  return (
    <p className="text-xs leading-relaxed">
      <strong>{FRAME_WORDS[forward.frame]}.</strong>{" "}
      F, B, L and R round the drone are where ↑, ↓, ← and → move it now — they do not turn with the nose.
      The red tick is the nose. The green is where both stations' light reaches; the line behind the drone is where it has been.
    </p>
  );
}

/** No station measured in this room: the stages, and Measure — the same as
 *  Auto's ② Position (auto/PositionStep.tsx), here because Manual has no flow. */
function NotMeasured({ session, run, drone, yaw, forward }: {
  session: Session; run: Run; drone: XY | null; yaw: number | null; forward: KeyForward;
}) {
  const station = useStation(session.radio?.state === "connected");
  const [outcome, setOutcome] = useState<{ tone: Tone; text: string } | null>(null);
  const working = station?.measuring === true;
  const flying = session.state === "busy";
  const measure = () => {
    setOutcome(null);
    void run(async () => {
      try {
        const r = await api.measureStation();
        setOutcome({ tone: "good", text: r.message });
      } catch (e) {
        setOutcome({ tone: "critical", text: e instanceof AgentError ? e.message : "The measurement did not work." });
        throw e;
      }
    }, "Measure the base stations");
  };
  return (
    <div className="grid gap-3 p-3">
      {session.decks_lost ? (
        // Not "not measured": the drone had its decks a moment ago (2026-10-24
        // — a restart over the radio unpowered them). Measuring cannot help.
        <Message tone="warning" text="The drone does not detect its decks now — the positioning deck and the camera. Switch the drone off and on with its button (or unplug the battery for 10 seconds): decks are only detected at power-on." />
      ) : (
        <Message tone="warning" text="The base stations are not measured from this drone yet, so the room cannot be drawn. Put the drone flat on the floor in view of both stations and press Measure — that spot becomes 0, 0." />
      )}
      {station?.connected && <StationStages station={station} />}
      {working && <Spinner label="Measuring — keep the drone still…" />}
      {outcome && !working && <Message tone={outcome.tone} text={outcome.text} />}
      <div>
        <Button variant="primary" onClick={measure}
                disabled={!station?.connected || working || flying || station.received.length === 0}>
          Measure from where the drone sits
        </Button>
      </div>
      {drone === null && yaw !== null && forward.deg !== null && <Compass yaw={yaw} forwardDeg={forward.deg} />}
    </div>
  );
}

/**
 * The arrows without a room: ↑ at the top, always, and the drone drawn turning
 * under them — the nose at (heading − ↑) — so a turn with A / D is seen as the
 * drone turning, not the keys. For flight with no position (takeoff frame).
 */
function Compass({ yaw, forwardDeg }: { yaw: number; forwardDeg: number }) {
  // Screen up is ↑; a nose this many degrees counter-clockwise of ↑ is drawn
  // rotated that way (SVG rotates clockwise, so negated).
  const nose = yaw - forwardDeg;
  const r = 0.62;
  return (
    <figure className="grid justify-items-center gap-1 border border-[var(--border)] bg-[var(--surface-2)] p-3">
      <svg viewBox="-1 -1 2 2" className="h-44 w-44" role="img"
           aria-label={`No position: ↑ is at the top; the drone's nose is ${Math.round(((nose % 360) + 540) % 360 - 180)}° from it`}>
        <circle cx={0} cy={0} r={0.86} style={{ fill: "none", stroke: "var(--border)", strokeWidth: 0.02 }} />
        {KEY_DIRECTIONS.map((d) => {
          const a = ((d.offsetDeg + 90) * Math.PI) / 180;          // screen: ↑ at the top
          const main = d.letter === "F";
          return (
            <text key={d.letter} x={Math.cos(a) * 0.86} y={-Math.sin(a) * 0.86 + 0.07} textAnchor="middle"
                  style={{ fill: main ? "var(--primary)" : "var(--foreground)", fontSize: 0.22, fontWeight: 800,
                           paintOrder: "stroke", stroke: "var(--surface-2)", strokeWidth: 0.06 }}>
              {d.letter}
            </text>
          );
        })}
        <g transform={`rotate(${-nose})`}>
          {[45, 135, 225, 315].map((deg) => {
            const a = (deg * Math.PI) / 180;
            return (
              <g key={deg}>
                <line x1={0} y1={0} x2={Math.cos(a) * r * 0.6} y2={Math.sin(a) * r * 0.6}
                      style={{ stroke: "var(--foreground)", strokeWidth: 0.05 }} />
                <circle cx={Math.cos(a) * r * 0.6} cy={Math.sin(a) * r * 0.6} r={0.13}
                        style={{ fill: "none", stroke: "var(--status-good)", strokeWidth: 0.04 }} />
              </g>
            );
          })}
          <line x1={0} y1={0} x2={0} y2={-r * 0.85} style={{ stroke: "var(--status-critical)", strokeWidth: 0.08, strokeLinecap: "round" }} />
        </g>
      </svg>
      <figcaption className="text-center text-xs">
        No position — ↑ (F) is the way the nose points at takeoff, and it stays there when A or D turn the
        drone. The red line is the nose now.
      </figcaption>
    </figure>
  );
}
