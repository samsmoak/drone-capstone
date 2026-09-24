/**
 * The drone in the room — where it is, how it is sitting, and what the motors
 * are doing, drawn as one picture.
 *
 * NO THREE.JS, DELIBERATELY. The scene is one body, four rotors, a floor grid
 * and a trail; three.js is ~170 KB gzipped for that, against a frontend bundle
 * that is 194 KB gzipped in total — it would roughly double the window's
 * JavaScript. (The .dmg is 48 MB, but almost all of that is the frozen agent;
 * see ../../../../docs/features/desktop/desktop-app.txt for the measurement.)
 * This is an axonometric projection and a 3×3 rotation matrix in about a
 * hundred lines, with no dependency and no change to the window's content
 * policy. Reach for three.js if this ever needs an orbitable camera or real
 * lighting.
 *
 * EVERY NUMBER HERE IS REAL: position from `stateEstimate.x/y`, height from the
 * frame's own `height_m` (metres above the ground captured at takeoff, not
 * Lighthouse z — see the invariant in CLAUDE.md), attitude from
 * `stabilizer.roll/pitch/yaw`, and rotor speed from `motor.m1..m4`. All of it
 * is already in the shared 10 Hz stream.
 *
 * THE ROTOR SPIN IS INDICATIVE, NOT LITERAL. A real Crazyflie rotor turns at a
 * few hundred revolutions a second; sampling its PWM ten times a second cannot
 * show that, and animating it honestly would just strobe. The spin rate is
 * scaled to something legible, and the pane says so.
 *
 * Telemetry reaches the draw loop through a ref, so 10 Hz frames redraw the
 * canvas without re-rendering the React tree.
 */

import { useEffect, useRef } from "react";
import type { History } from "@/App";
import type { Telemetry } from "@/lib/agent";

/** The room drawn, in metres. Positions outside it are clamped for the picture
 *  only — the readouts beside it always report what the drone actually said. */
const ROOM_M = 4;
const CEILING_M = 2;

/** Visible revolutions per second at full PWM. Legible, not literal. */
const MAX_RPS = 3;

const DEG = Math.PI / 180;
const COS30 = Math.cos(30 * DEG);
const SIN30 = Math.sin(30 * DEG);

type Vec3 = [number, number, number];

/** Aerospace ZYX: yaw about z, then pitch about y, then roll about x. The sign
 *  convention is the firmware's own; the numeric readouts are authoritative. */
function rotate([x, y, z]: Vec3, roll: number, pitch: number, yaw: number): Vec3 {
  const cr = Math.cos(roll * DEG), sr = Math.sin(roll * DEG);
  const cp = Math.cos(pitch * DEG), sp = Math.sin(pitch * DEG);
  const cy = Math.cos(yaw * DEG), sy = Math.sin(yaw * DEG);

  // Roll about x
  let [a, b, c] = [x, y * cr - z * sr, y * sr + z * cr];
  // Pitch about y
  [a, b, c] = [a * cp + c * sp, b, -a * sp + c * cp];
  // Yaw about z
  return [a * cy - b * sy, a * sy + b * cy, c];
}

export function SceneView({ telemetry, history, active }: {
  telemetry: Telemetry | null;
  history: History;
  /**
   * Whether the Scene tab is the one showing.
   *
   * The panels stay mounted across a tab switch so this one keeps its trail —
   * but a requestAnimationFrame loop that keeps running behind a hidden tab is
   * 60 repaints a second of a canvas nobody can see, on a laptop that is also
   * flying a drone. The loop only runs while the tab is visible.
   */
  active: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  // The draw loop reads these instead of props, so a 10 Hz frame costs a
  // canvas repaint and not a React render. Synced in an effect rather than
  // written during render, which React forbids.
  const latest = useRef<Telemetry | null>(telemetry);
  const trail = useRef<History>(history);
  useEffect(() => {
    latest.current = telemetry;
    trail.current = history;
  }, [telemetry, history]);

  useEffect(() => {
    if (!active) return;
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const spin = [0, 0, 0, 0];
    let raf = 0;
    let last = performance.now();

    // The token values, cached. getComputedStyle forces a style recalculation,
    // and doing that inside the draw call meant one per frame — sixty a second
    // to fetch six strings that only change when the theme does. Re-read every
    // 30 frames, which catches a theme switch within half a second.
    let palette = readPalette(el);
    let sincePalette = 0;

    // Backing store in device pixels, drawing in CSS pixels: a 1px grid line
    // on a Retina panel is otherwise a 2px smear.
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const { width, height } = el.getBoundingClientRect();
      el.width = Math.max(1, Math.round(width * dpr));
      el.height = Math.max(1, Math.round(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    // The tab was display:none until this frame, so the first measurement can
    // legitimately be 0x0. Re-measure for a few frames; a canvas that starts
    // 0-sized otherwise stays blank until the window itself is resized, which
    // is exactly the "scene stopped coming" symptom.
    let settle = 0;
    const observer = new ResizeObserver(resize);
    observer.observe(el);

    const frame = (time: number) => {
      const dt = Math.min(0.1, (time - last) / 1000);
      last = time;
      if (settle < 10) { settle += 1; resize(); }

      if (sincePalette++ % 30 === 0) palette = readPalette(el);

      const telem = latest.current;
      const values = telem?.values ?? {};
      if (!reduced) {
        for (let i = 0; i < 4; i++) {
          const pwm = (values[`motor.m${i + 1}`] ?? 0) / 65535;
          spin[i] = (spin[i] + pwm * MAX_RPS * 2 * Math.PI * dt) % (2 * Math.PI);
        }
      }

      draw(ctx, el, palette, {
        x: values["stateEstimate.x"] ?? 0,
        y: values["stateEstimate.y"] ?? 0,
        z: telem?.height_m ?? 0,
        roll: values["stabilizer.roll"] ?? 0,
        pitch: values["stabilizer.pitch"] ?? 0,
        yaw: values["stabilizer.yaw"] ?? 0,
        motors: [0, 1, 2, 3].map((i) => (values[`motor.m${i + 1}`] ?? 0) / 65535),
        spin,
        trail: trail.current,
        known: telem !== null,
      });

      raf = window.requestAnimationFrame(frame);
    };
    raf = window.requestAnimationFrame(frame);

    return () => {
      window.cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [active]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Its own floor: the scene is ONLY a canvas, so unlike Vitals and
          Camera it has no content to give it height, and in a content-tall
          console it collapsed to 0 px (2026-09-24). A floor here fixes the
          Scene alone — making the whole console fill instead changed the
          Vitals split and cut off its compass. */}
      <div className="relative min-h-[26rem] flex-1 bg-[var(--console)]">
        <canvas
          ref={canvas}
          className="absolute inset-0 h-full w-full"
          role="img"
          aria-label={
            telemetry
              ? "The drone's position and attitude in the room, drawn to scale"
              : "No telemetry — nothing to draw"
          }
        />
      </div>
      <p className="mono border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">
        {ROOM_M} × {ROOM_M} × {CEILING_M} m room · position and attitude to scale · rotor spin
        indicative, not literal
      </p>
    </div>
  );
}

type Scene = {
  x: number; y: number; z: number;
  roll: number; pitch: number; yaw: number;
  motors: number[];
  spin: number[];
  trail: History;
  known: boolean;
};

type Palette = { ink: string; dim: string; line: string; primary: string; warning: string; surface: string };

/** The tokens, resolved once. Canvas cannot reference a CSS variable. */
function readPalette(el: HTMLElement): Palette {
  const style = getComputedStyle(el);
  const pick = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ink: pick("--console-ink", "#000"),
    dim: pick("--console-dim", "#888"),
    line: pick("--console-line", "#ccc"),
    primary: pick("--primary", "#1c5cab"),
    warning: pick("--status-warning", "#fab219"),
    surface: pick("--surface", "#fff"),
  };
}

function draw(ctx: CanvasRenderingContext2D, el: HTMLCanvasElement, palette: Palette, s: Scene) {
  const { width, height } = el.getBoundingClientRect();
  const { ink, dim, line, primary, warning } = palette;

  ctx.clearRect(0, 0, width, height);

  // Fit the room's diagonal into the shorter side, with room for the ceiling.
  const scale = Math.min(width / (ROOM_M * 2 * COS30), height / (ROOM_M * 2 * SIN30 + CEILING_M)) * 0.82;
  const cx = width / 2;
  const cy = height / 2 + (ROOM_M * SIN30 * scale) / 2;

  const project = ([x, y, z]: Vec3): [number, number] => [
    cx + (x - y) * COS30 * scale,
    cy + (x + y) * SIN30 * scale - z * scale,
  ];

  const half = ROOM_M / 2;
  const clamp = (v: number) => Math.max(-half, Math.min(half, v));

  // ── the room ──────────────────────────────────────────────────────
  ctx.lineWidth = 1;
  ctx.strokeStyle = line;
  for (let i = 0; i <= ROOM_M * 2; i++) {
    const t = -half + i * 0.5;
    const [ax, ay] = project([t, -half, 0]);
    const [bx, by] = project([t, half, 0]);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    const [px, py] = project([-half, t, 0]);
    const [qx, qy] = project([half, t, 0]);
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(qx, qy); ctx.stroke();
  }

  // Corner posts, so height reads as height rather than as distance.
  ctx.strokeStyle = dim;
  for (const [px, py] of [[-half, -half], [half, -half], [half, half], [-half, half]] as const) {
    const [ax, ay] = project([px, py, 0]);
    const [bx, by] = project([px, py, CEILING_M]);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  }

  if (!s.known) {
    ctx.fillStyle = dim;
    ctx.font = '600 11px ui-monospace, SFMono-Regular, Menlo, monospace';
    ctx.textAlign = "center";
    ctx.fillText("NO TELEMETRY", cx, cy - 8);
    return;
  }

  const dx = clamp(s.x), dy = clamp(s.y), dz = Math.max(0, Math.min(CEILING_M, s.z));

  // ── the trail ─────────────────────────────────────────────────────
  // Every fifth frame: 10 Hz for a minute is 600 points, and 120 is plenty to
  // read a path from.
  const points = s.trail.filter((_, i) => i % 5 === 0);
  if (points.length > 1) {
    ctx.lineWidth = 1.5;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      ctx.globalAlpha = 0.08 + 0.5 * (i / points.length);
      ctx.strokeStyle = primary;
      ctx.beginPath();
      const [ax, ay] = project([clamp(a.values["stateEstimate.x"] ?? 0), clamp(a.values["stateEstimate.y"] ?? 0), Math.max(0, a.height_m ?? 0)]);
      const [bx, by] = project([clamp(b.values["stateEstimate.x"] ?? 0), clamp(b.values["stateEstimate.y"] ?? 0), Math.max(0, b.height_m ?? 0)]);
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // ── the shadow and the drop line: height, made legible ────────────
  const [gx, gy] = project([dx, dy, 0]);
  ctx.strokeStyle = dim;
  ctx.setLineDash([3, 3]);
  ctx.lineWidth = 1;
  const [bodyX, bodyY] = project([dx, dy, dz]);
  ctx.beginPath(); ctx.moveTo(gx, gy); ctx.lineTo(bodyX, bodyY); ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.ellipse(gx, gy, 9 * COS30, 9 * SIN30, 0, 0, 2 * Math.PI);
  ctx.fillStyle = dim;
  ctx.globalAlpha = 0.35;
  ctx.fill();
  ctx.globalAlpha = 1;

  // ── the drone ─────────────────────────────────────────────────────
  // A Crazyflie's arms sit at 45° to its forward axis: motors 1..4 are
  // front-right, rear-right, rear-left, front-left looking down.
  const ARM = 0.055;                 // metres, roughly the real span
  const ARMS: Vec3[] = [
    [ARM, -ARM, 0], [-ARM, -ARM, 0], [-ARM, ARM, 0], [ARM, ARM, 0],
  ];
  // Drawn far larger than life: at this room scale a 9 cm drone would be four
  // pixels across and its attitude unreadable, which is the whole point of the
  // view. The room's grid carries the actual scale.
  const BODY_GAIN = 9;

  const centre: Vec3 = [dx, dy, dz];
  const tips = ARMS.map((arm) => {
    const [rx, ry, rz] = rotate(arm.map((v) => v * BODY_GAIN) as Vec3, s.roll, s.pitch, s.yaw);
    return project([centre[0] + rx, centre[1] + ry, centre[2] + rz]);
  });

  ctx.lineWidth = 2.5;
  ctx.strokeStyle = ink;
  for (const [tx, ty] of tips) {
    ctx.beginPath(); ctx.moveTo(bodyX, bodyY); ctx.lineTo(tx, ty); ctx.stroke();
  }

  // Which way is forward: the arms between motors 1 and 4.
  ctx.strokeStyle = warning;
  ctx.lineWidth = 3;
  const [fx, fy] = project([
    centre[0] + rotate([ARM * BODY_GAIN * 1.7, 0, 0], s.roll, s.pitch, s.yaw)[0],
    centre[1] + rotate([ARM * BODY_GAIN * 1.7, 0, 0], s.roll, s.pitch, s.yaw)[1],
    centre[2] + rotate([ARM * BODY_GAIN * 1.7, 0, 0], s.roll, s.pitch, s.yaw)[2],
  ]);
  ctx.beginPath(); ctx.moveTo(bodyX, bodyY); ctx.lineTo(fx, fy); ctx.stroke();

  // Rotors: a disc per motor, two blades at the current angle. The disc's
  // opacity follows the PWM, so a motor at rest is visibly at rest.
  tips.forEach(([tx, ty], i) => {
    const r = 13;
    ctx.globalAlpha = 0.18 + 0.5 * s.motors[i];
    ctx.fillStyle = primary;
    ctx.beginPath();
    ctx.ellipse(tx, ty, r * COS30, r * SIN30 * 1.6, 0, 0, 2 * Math.PI);
    ctx.fill();
    ctx.globalAlpha = 1;

    ctx.strokeStyle = ink;
    ctx.lineWidth = 1.5;
    for (const offset of [0, Math.PI / 2]) {
      const a = s.spin[i] + offset;
      ctx.beginPath();
      ctx.moveTo(tx - Math.cos(a) * r * COS30, ty - Math.sin(a) * r * SIN30 * 1.6);
      ctx.lineTo(tx + Math.cos(a) * r * COS30, ty + Math.sin(a) * r * SIN30 * 1.6);
      ctx.stroke();
    }
  });

  ctx.fillStyle = ink;
  ctx.beginPath();
  ctx.arc(bodyX, bodyY, 4, 0, 2 * Math.PI);
  ctx.fill();

  // ── the readout ───────────────────────────────────────────────────
  // The clamped drawing above must never be the only thing on screen: these
  // are the drone's actual figures, whether or not it is inside the box.
  ctx.font = '11px ui-monospace, SFMono-Regular, Menlo, monospace';
  ctx.textAlign = "left";
  ctx.fillStyle = dim;
  const rows = [
    `x ${s.x.toFixed(2)} m   y ${s.y.toFixed(2)} m   z ${s.z.toFixed(2)} m`,
    `roll ${s.roll.toFixed(1)}°   pitch ${s.pitch.toFixed(1)}°   yaw ${s.yaw.toFixed(1)}°`,
  ];
  rows.forEach((row, i) => ctx.fillText(row, 10, 16 + i * 14));

  if (Math.abs(s.x) > half || Math.abs(s.y) > half || s.z > CEILING_M) {
    ctx.fillStyle = warning;
    ctx.fillText("outside the drawn room — figures above are the real ones", 10, 16 + rows.length * 14);
  }
}
