/**
 * The room map in 3-D: the room's flying space, its obstacles at their real
 * height, the path at the heights it is flown, and the drone — orbitable,
 * selectable and editable.
 *
 * THREE.JS, LOADED ONLY WHEN THIS OPENS. SceneView.tsx drew its scene by hand
 * to keep three.js (~170 KB gzipped) out of the window, and said to reach for
 * it "if this ever needs an orbitable camera". This is that: orbiting, picking
 * an object with the mouse, and dragging its sides. RoomMap imports this file
 * with React.lazy, so the library is a separate chunk fetched the first time
 * 3-D is opened — the window starts exactly as fast as before.
 *
 * THE WORLD IS THE ROOM FRAME, z UP: x left→right (length), y front→back
 * (width), z up (height), in metres, with no conversion anywhere. Heights
 * are above the floor captured at takeoff (CLAUDE.md invariant 4), which is
 * what the path's z already is.
 *
 * SELECTING ONE THING FADES THE REST (PlanCanvas does the same): the room
 * (its walls) or one obstacle. A selected object grows handles — its sides
 * for length and width, its top for height, its body to move it — and every
 * drag goes through the same clamping to the room's map as the 2-D plan
 * (geometry.ts). The form beside the map shows the same numbers, and is the
 * keyboard's way to change them (WCAG 2.2, 2.5.7: dragging always has a
 * single-pointer alternative).
 *
 * RENDERED ON DEMAND: a frame is drawn only when something changes — a drag,
 * an orbit, a 10 Hz telemetry frame — never 60 times a second beside the
 * flight loop. The window's own content policy is unchanged: no fonts or
 * workers are fetched (labels are HTML, not a downloaded font).
 */

import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { Edges, GizmoHelper, GizmoViewport, Line, OrbitControls } from "@react-three/drei";
import {
  BufferGeometry, CanvasTexture, Color, DoubleSide, Float32BufferAttribute, FrontSide, Plane, Quaternion, Shape,
  SRGBColorSpace, Vector3, type PerspectiveCamera,
} from "three";
import type { Geofence, InspectionPoint, Obstacle, OuterBound, Problem, XY } from "@/lib/agent";
import {
  circleFence, circleOf, clamp, cm, dimensionsOf, mapBox, MIN_SIZE_M, moveObstacle, obstacleFrom,
  rectangleFence, rectangleOf, resizeRectangle, type Box,
} from "./geometry";
import { landsAt, legsOf, unflownIds, type PathSource } from "./path";
import { insideOutline, type SpaceLayer } from "./space";
import { isRoomObject, sameHandle, type Handle, type PointState } from "./PlanCanvas";

/** What of drei's OrbitControls this file uses — the orbit's centre, and
 *  pausing it while a handle is dragged. */
type OrbitControlsImpl = { target: Vector3; update: () => void; enabled: boolean };

export type CameraPreset = "three-quarter" | "top" | "front" | "side" | "fit";

export type Edit3D = {
  selected: Handle | null;
  onSelect: (handle: Handle | null) => void;
  onFence: (fence: Geofence) => void;
  onObstacle: (id: string, next: Obstacle) => void;
  onPoint: (id: string, change: Partial<InspectionPoint>) => void;
  onHome: (at: XY) => void;
  onPlace?: (at: XY) => void;
  placing?: string | null;
  onPointMenu?: (id: string, at: { x: number; y: number }) => void;
  /** The flight system's ceiling: the room's height is held under it. */
  zMax: number;
};

export type Room3DProps = {
  outer: OuterBound;
  fence: Geofence | null;
  obstacles: Obstacle[];
  path: PathSource | null;
  takeoffHeight: number;
  problems: Problem[];
  drone: XY | null;
  /** Height above the floor, when a flight is reporting it. */
  droneHeight?: number | null;
  /** Degrees, the firmware's stabilizer.yaw. */
  droneYaw?: number | null;
  progress?: Record<string, PointState>;
  editing?: Edit3D;
  /** When not editing: what to highlight (a click still selects to look). */
  selected?: Handle | null;
  onSelect?: (handle: Handle | null) => void;
  /** A camera move asked for from outside (the toolbar); `n` repeats it. */
  camera: { preset: CameraPreset; n: number };
  /** The flyable space (space.ts): a see-through volume the plan sits inside. */
  space?: SpaceLayer | null;
  label: string;
};

type Palette = {
  primary: string; warning: string; good: string; critical: string;
  foreground: string; muted: string; grid: string; surface: string; floor: string;
};

function readPalette(el: HTMLElement | null): Palette {
  const css = el ? getComputedStyle(el) : null;
  const v = (name: string, fallback: string) => css?.getPropertyValue(name).trim() || fallback;
  return {
    primary: v("--primary", "#1c5cab"), warning: v("--status-warning", "#fab219"),
    good: v("--status-good", "#0ca30c"), critical: v("--status-critical", "#d03b3b"),
    foreground: v("--foreground", "#0b0b0b"), muted: v("--muted", "#52514e"),
    grid: v("--grid", "#ebebe8"), surface: v("--surface", "#ffffff"), floor: v("--surface-2", "#f5f5f3"),
  };
}

/** Re-read the tokens when the theme changes — the app's own switch sets
 *  data-theme on <html>; the system's is a media query. */
function usePalette(el: HTMLElement | null): Palette {
  const [palette, setPalette] = useState(() => readPalette(el));
  useEffect(() => {
    const update = () => setPalette(readPalette(el));
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    return () => { observer.disconnect(); media.removeEventListener("change", update); };
  }, [el]);
  return palette;
}

const FADED = 0.18;
/** The drone is drawn 1.5× its 92 mm size so it can be found in a 4 m room. */
const DRONE_SCALE = 1.5;

export default function Room3D(props: Room3DProps) {
  const host = useRef<HTMLDivElement>(null);
  const [hostEl, setHostEl] = useState<HTMLDivElement | null>(null);
  useEffect(() => setHostEl(host.current), []);
  const palette = usePalette(hostEl);
  const box = mapBox(props.outer);
  // Where a press started, so an orbit drag that ends on empty space is not
  // also a click that clears the selection.
  const pressed = useRef<{ x: number; y: number } | null>(null);
  const moved = (e: { clientX: number; clientY: number }) =>
    pressed.current !== null && Math.hypot(e.clientX - pressed.current.x, e.clientY - pressed.current.y) > 5;

  return (
    <div
      ref={host}
      className="relative h-full w-full min-w-0 touch-none select-none overflow-hidden bg-[var(--surface-2)]"
      onPointerDownCapture={(e) => { pressed.current = { x: e.clientX, y: e.clientY }; }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <Canvas
        frameloop="demand"
        dpr={[1, 2]}
        camera={{ up: [0, 0, 1], fov: 45, near: 0.02, far: 200, position: [box.xMin - 3, box.yMin - 4, 3.5] }}
        onPointerMissed={(e) => {
          if (moved(e)) return;
          const select = props.editing?.onSelect ?? props.onSelect;
          if (!props.editing?.placing) select?.(null);
        }}
        aria-label={props.label}
        role="img"
      >
        <Suspense fallback={null}>
          <Scene {...props} palette={palette} box={box} moved={moved} />
        </Suspense>
      </Canvas>
    </div>
  );
}

// ── the scene ────────────────────────────────────────────────────────────

function Scene({
  outer, fence, obstacles, path, takeoffHeight, problems, drone, droneHeight, droneYaw,
  progress, editing, selected: shownSelected, onSelect, camera, palette, box, moved, space = null,
}: Room3DProps & { palette: Palette; box: Box; moved: (e: { clientX: number; clientY: number }) => boolean }) {
  const current = editing?.selected ?? shownSelected ?? null;
  const select = editing?.onSelect ?? onSelect;
  const focus = isRoomObject(current) ? current : null;
  const fenceMine = focus?.kind === "fence" || focus?.kind === "vertex";
  const bad = new Set(problems.filter((p) => p.severity === "error").map((p) => p.where));

  // The room's display ceiling: the flying space's top with headroom, and at
  // least as tall as the tallest obstacle the operator gave a height.
  const tallest = Math.max(0, ...obstacles.map((o) => o.height_m ?? 0));
  const ceiling = Math.max(2.0, (fence?.z_max ?? 1) + 0.8, tallest + 0.2);

  const pick = (handle: Handle) => (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (moved(e.nativeEvent)) return;
    if (editing?.placing && editing.onPlace) {
      editing.onPlace([e.point.x, e.point.y]);
      return;
    }
    select?.(handle);
  };
  const focusOn = useFocus(box, ceiling);

  return (
    <>
      <ambientLight intensity={0.75} />
      <directionalLight position={[box.xMin - 2, box.yMin - 3, 6]} intensity={1.1} />
      <CameraRig box={box} ceiling={ceiling} camera={camera} />
      <OrbitControls makeDefault enableDamping={false} maxPolarAngle={Math.PI / 2 - 0.01}
                     minDistance={0.3} maxDistance={40} />

      <Floor box={box} outer={outer} palette={palette}
             onClick={(e) => {
               if (moved(e.nativeEvent)) return;
               e.stopPropagation();
               // Placing: the click puts the thing here. Otherwise a click on
               // empty floor selects NOTHING — every object shown equally.
               // (The floor has a handler, so onPointerMissed never fires for
               // it: without this, empty floor kept the last selection.)
               if (editing?.placing && editing.onPlace) editing.onPlace([e.point.x, e.point.y]);
               else select?.(null);
             }} />

      {space && <SpaceVolume space={space} path={path} palette={palette} />}
      {fence && (
        <FenceWalls fence={fence} palette={palette} mine={fenceMine} faded={!!focus && !fenceMine}
                    onClick={pick({ kind: "fence" })}
                    onDoubleClick={() => focusOn(fence.vertices, (fence.z_min + fence.z_max) / 2)} />
      )}
      {fence && editing && fenceMine && (
        <FenceHandles fence={fence} box={box} zMax={editing.zMax} onFence={editing.onFence} palette={palette} />
      )}

      {obstacles.map((o) => {
        const mine = sameHandle(current, { kind: "obstacle", id: o.id });
        return (
          <ObstacleBody key={o.id} obstacle={o} ceiling={ceiling} palette={palette} mine={mine}
                        faded={!!focus && !mine}
                        movable={mine && !!editing}
                        onMove={(dx, dy) => editing?.onObstacle(o.id, moveObstacle(o, dx, dy, box))}
                        onClick={pick({ kind: "obstacle", id: o.id })}
                        onDoubleClick={() => focusOn(o.kind === "circle"
                          ? [[o.points[0][0] - (o.radius ?? 0), o.points[0][1]], [o.points[0][0] + (o.radius ?? 0), o.points[0][1]]]
                          : o.points, (o.height_m ?? ceiling) / 2)} />
        );
      })}
      {editing && focus?.kind === "obstacle" && (() => {
        const o = obstacles.find((item) => item.id === focus.id);
        return o ? (
          <ObstacleHandles obstacle={o} box={box} ceiling={ceiling} palette={palette}
                           onChange={(next) => editing.onObstacle(o.id, next)} />
        ) : null;
      })()}

      {path && (
        <PathLayer path={path} takeoffHeight={takeoffHeight} bad={bad} palette={palette}
                   faded={!!focus} progress={progress} editing={editing} box={box}
                   current={current} select={select} moved={moved} />
      )}

      {drone && <Drone at={drone} height={droneHeight ?? 0} yaw={droneYaw ?? 0} palette={palette} box={box} />}

      <GizmoHelper alignment="bottom-right" margin={[56, 56]}>
        <GizmoViewport labels={["L", "W", "H"]} axisColors={[palette.critical, palette.good, palette.primary]}
                       labelColor={palette.surface} />
      </GizmoHelper>
    </>
  );
}

// ── the camera ───────────────────────────────────────────────────────────

/** The toolbar's views, and the start: a three-quarter view of the whole room. */
function CameraRig({ box, ceiling, camera }: { box: Box; ceiling: number; camera: Room3DProps["camera"] }) {
  const { camera: cam, controls, invalidate, size: viewport } = useThree();
  // Has the operator turned the camera since the last preset? Then a resize
  // leaves their view alone; otherwise the preset is re-fitted to the new
  // shape — dragged narrower by the editor's divider, a view framed for a
  // wide box cropped the room at both sides (2026-09-29).
  const userMoved = useRef(false);
  const lastAsked = useRef("");
  useEffect(() => {
    const orbit = controls as unknown as (OrbitControlsImpl & {
      addEventListener?: (type: string, fn: () => void) => void;
      removeEventListener?: (type: string, fn: () => void) => void;
    }) | null;
    const moved = () => { userMoved.current = true; };
    orbit?.addEventListener?.("start", moved);
    return () => orbit?.removeEventListener?.("start", moved);
  }, [controls]);
  useEffect(() => {
    const asked = `${camera.preset}:${camera.n}`;
    const isNewRequest = asked !== lastAsked.current;
    if (!isNewRequest && userMoved.current) return;     // a resize, and they have looked around
    lastAsked.current = asked;
    userMoved.current = false;
    const orbit = controls as unknown as OrbitControlsImpl | null;
    const cx = (box.xMin + box.xMax) / 2;
    const cy = (box.yMin + box.yMax) / 2;
    const extent = Math.max(box.xMax - box.xMin, box.yMax - box.yMin, 1);
    // The field of view is vertical: a tall, narrow view needs the camera
    // further back to keep the room's width in frame.
    const aspect = viewport.height > 0 ? viewport.width / viewport.height : 1;
    const size = extent * Math.max(1, 1.1 / aspect);
    const target = new Vector3(cx, cy, Math.min(0.5, ceiling / 4));
    const at: Record<CameraPreset, [number, number, number]> = {
      "three-quarter": [cx - 0.5 * size, cy - 0.95 * size, 0.8 * size],
      fit: [cx - 0.6 * size, cy - 1.15 * size, 0.95 * size],
      top: [cx, cy - 0.001, 2.1 * size],
      front: [cx, cy - 2.0 * size, 0.6],
      side: [cx + 2.0 * size, cy, 0.6],
    };
    cam.position.set(...at[camera.preset]);
    (cam as PerspectiveCamera).up.set(0, 0, 1);
    cam.lookAt(target);
    if (orbit) {
      orbit.target.copy(target);
      orbit.update();
    }
    invalidate();
  }, [camera.preset, camera.n, box.xMin, box.xMax, box.yMin, box.yMax, ceiling, cam, controls, invalidate,
      viewport.width, viewport.height]);
  return null;
}

/** Swing the orbit round one object: double-click it. */
function useFocus(box: Box, ceiling: number) {
  const { camera, controls, invalidate } = useThree();
  return (points: XY[], z: number) => {
    const orbit = controls as unknown as OrbitControlsImpl | null;
    if (!orbit || points.length === 0) return;
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    const centre = new Vector3((Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2,
                               clamp(z, 0, ceiling));
    const size = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 0.4);
    const direction = camera.position.clone().sub(orbit.target).normalize();
    const distance = clamp(size * 2.8, 1.0, Math.max(box.xMax - box.xMin, box.yMax - box.yMin) * 2.5);
    orbit.target.copy(centre);
    camera.position.copy(centre.clone().add(direction.multiplyScalar(distance)));
    orbit.update();
    invalidate();
  };
}

// ── the floor and the room ───────────────────────────────────────────────

function Floor({ box, outer, palette, onClick }: {
  box: Box; outer: OuterBound; palette: Palette; onClick: (e: ThreeEvent<MouseEvent>) => void;
}) {
  const lines = useMemo(() => {
    const out: [number, number, number][][] = [];
    for (let x = Math.ceil(box.xMin * 2) / 2; x <= box.xMax + 1e-9; x += 0.5) {
      out.push([[x, box.yMin, 0.001], [x, box.yMax, 0.001]]);
    }
    for (let y = Math.ceil(box.yMin * 2) / 2; y <= box.yMax + 1e-9; y += 0.5) {
      out.push([[box.xMin, y, 0.001], [box.xMax, y, 0.001]]);
    }
    return out;
  }, [box.xMin, box.xMax, box.yMin, box.yMax]);
  const outline = [...outer.vertices, outer.vertices[0]].map(([x, y]) => [x, y, 0.002] as [number, number, number]);
  const w = box.xMax - box.xMin;
  const d = box.yMax - box.yMin;
  return (
    <group>
      <mesh position={[(box.xMin + box.xMax) / 2, (box.yMin + box.yMax) / 2, 0]} onClick={onClick}>
        <planeGeometry args={[w, d]} />
        <meshBasicMaterial color={palette.floor} />
      </mesh>
      {lines.map((points, i) => <Line key={i} points={points} color={palette.grid} lineWidth={1} />)}
      <Line points={outline} color={palette.muted} lineWidth={1.2} dashed dashSize={0.1} gapSize={0.08} />
      {/* where "from left" and "from front" are measured from */}
      <TextLabel text="front-left · 0, 0" position={[box.xMin + 0.02, box.yMin - 0.12, 0]} palette={palette} quiet />
    </group>
  );
}

/**
 * The room's walls, FACING INWARD — a dollhouse. Drawn one-sided, a wall is
 * seen (and clickable) only from inside the room: the walls between the
 * camera and the room vanish, the far ones remain. Double-sided, the near wall
 * caught every click aimed at the floor inside the room and selected the room
 * — you could not click empty floor to select nothing (2026-09-29).
 *
 * Which way a quad faces follows its winding: for a counter-clockwise outline
 * (positive area) edge v1→v2 extruded upwards faces OUTWARD, so it is wound
 * the other way; a clockwise outline is already inward.
 */
function wallGeometry(vertices: XY[], zMin: number, zMax: number): BufferGeometry {
  const area = vertices.reduce((sum, [x1, y1], i) => {
    const [x2, y2] = vertices[(i + 1) % vertices.length];
    return sum + (x1 * y2 - x2 * y1);
  }, 0);
  const positions: number[] = [];
  vertices.forEach((v1, i) => {
    const v2 = vertices[(i + 1) % vertices.length];
    const [[ax, ay], [bx, by]] = area > 0 ? [v2, v1] : [v1, v2];
    positions.push(ax, ay, zMin, bx, by, zMin, bx, by, zMax, ax, ay, zMin, bx, by, zMax, ax, ay, zMax);
  });
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

function FenceWalls({ fence, palette, mine, faded, onClick, onDoubleClick }: {
  fence: Geofence; palette: Palette; mine: boolean; faded: boolean;
  onClick: (e: ThreeEvent<MouseEvent>) => void; onDoubleClick: () => void;
}) {
  const walls = useMemo(() => wallGeometry(fence.vertices, fence.z_min, fence.z_max),
    [fence.vertices, fence.z_min, fence.z_max]);
  const floorShape = useMemo(() => {
    const shape = new Shape();
    fence.vertices.forEach(([x, y], i) => (i === 0 ? shape.moveTo(x, y) : shape.lineTo(x, y)));
    shape.closePath();
    return shape;
  }, [fence.vertices]);
  useEffect(() => () => walls.dispose(), [walls]);
  const ring = (z: number) => [...fence.vertices, fence.vertices[0]].map(([x, y]) => [x, y, z] as [number, number, number]);
  const posts = fence.vertices.filter((_, i) => fence.shape !== "circle" || i % 4 === 0);
  const opacity = faded ? FADED : 1;
  return (
    <group>
      <mesh geometry={walls} onClick={onClick} onDoubleClick={(e) => { e.stopPropagation(); onDoubleClick(); }}>
        <meshBasicMaterial color={palette.primary} transparent opacity={(mine ? 0.2 : 0.09) * opacity}
                           side={FrontSide} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0, 0.003]}>
        <shapeGeometry args={[floorShape]} />
        <meshBasicMaterial color={palette.primary} transparent opacity={(mine ? 0.16 : 0.07) * opacity} depthWrite={false} />
      </mesh>
      <Line points={ring(fence.z_min)} color={palette.primary} lineWidth={mine ? 3 : 1.6} transparent opacity={opacity} />
      <Line points={ring(fence.z_max)} color={palette.primary} lineWidth={mine ? 3 : 1.6} transparent opacity={opacity} />
      <Line points={ring(0.004)} color={palette.primary} lineWidth={1} transparent opacity={0.5 * opacity} />
      {posts.map(([x, y], i) => (
        <Line key={i} points={[[x, y, 0], [x, y, fence.z_max]]} color={palette.primary} lineWidth={1}
              transparent opacity={0.6 * opacity} />
      ))}
    </group>
  );
}

// ── the flyable space ────────────────────────────────────────────────────

/** Where the drone's position can be trusted, as a see-through green volume:
 *  faint walls you look through to the room, the plan and the drone, its
 *  outline at the bottom and top, and — for a prediction — its outline at
 *  every height, so the blob's shape reads in depth. Any point of the plan
 *  outside it is ringed red at its height. */
function SpaceVolume({ space, path, palette }: { space: SpaceLayer; path: PathSource | null; palette: Palette }) {
  const walls = useMemo(() => wallGeometry(space.vertices, space.z_min, space.z_max),
    [space.vertices, space.z_min, space.z_max]);
  useEffect(() => () => walls.dispose(), [walls]);
  const ring = (vertices: XY[], z: number) =>
    [...vertices, vertices[0]].map(([x, y]) => [x, y, z] as [number, number, number]);
  const outside = (path?.points ?? []).filter((p) => !insideOutline([p.x_m, p.y_m], space.vertices));
  const dashed = space.kind !== "measured";
  return (
    <group>
      <mesh geometry={walls}>
        <meshBasicMaterial color={palette.good} transparent opacity={0.1} side={DoubleSide} depthWrite={false} />
      </mesh>
      <Line points={ring(space.vertices, space.z_min)} color={palette.good} lineWidth={1.6}
            dashed={dashed} dashSize={0.08} gapSize={0.05} />
      <Line points={ring(space.vertices, space.z_max)} color={palette.good} lineWidth={1.6}
            dashed={dashed} dashSize={0.08} gapSize={0.05} />
      {(space.slices ?? []).filter((sl) => sl.outline.length >= 3).map((sl) => (
        <Line key={sl.z_m} points={ring(sl.outline, sl.z_m)} color={palette.good} lineWidth={1}
              transparent opacity={0.45} />
      ))}
      {outside.map((p) => (
        <mesh key={p.id} position={[p.x_m, p.y_m, p.z_m]}>
          <torusGeometry args={[0.12, 0.012, 8, 32]} />
          <meshBasicMaterial color={palette.critical} />
        </mesh>
      ))}
    </group>
  );
}

// ── obstacles ────────────────────────────────────────────────────────────

function ObstacleBody({ obstacle: o, ceiling, palette, mine, faded, movable, onMove, onClick, onDoubleClick }: {
  obstacle: Obstacle; ceiling: number; palette: Palette; mine: boolean; faded: boolean;
  movable: boolean; onMove: (dx: number, dy: number) => void;
  onClick: (e: ThreeEvent<MouseEvent>) => void; onDoubleClick: () => void;
}) {
  const height = o.height_m ?? ceiling;
  const full = o.height_m === null || o.height_m === undefined;
  const drag = useFloorDrag(movable, (dx, dy) => onMove(dx, dy));
  const colour = new Color(palette.warning);
  const material = (
    <meshStandardMaterial color={colour} transparent opacity={(faded ? FADED : full ? 0.45 : 0.8)}
                          depthWrite={!faded && !full} />
  );
  const edges = <Edges color={mine ? palette.foreground : palette.warning} lineWidth={mine ? 2.5 : 1} />;
  const events = { onClick, onDoubleClick: (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onDoubleClick(); }, ...drag };
  let body: ReactNode;
  let labelAt: [number, number, number];
  if (o.kind === "circle") {
    const [cx, cy] = o.points[0];
    const r = o.radius ?? MIN_SIZE_M;
    body = (
      <mesh position={[cx, cy, height / 2]} rotation={[Math.PI / 2, 0, 0]} {...events}>
        <cylinderGeometry args={[r, r, height, 32]} />{material}{edges}
      </mesh>
    );
    labelAt = [cx, cy, height];
  } else if (o.kind === "rectangle") {
    const [[x1, y1], [x2, y2]] = o.points;
    body = (
      <mesh position={[(x1 + x2) / 2, (y1 + y2) / 2, height / 2]} {...events}>
        <boxGeometry args={[Math.abs(x2 - x1), Math.abs(y2 - y1), height]} />{material}{edges}
      </mesh>
    );
    labelAt = [(x1 + x2) / 2, (y1 + y2) / 2, height];
  } else {
    const [[x1, y1], [x2, y2]] = o.points;
    const length = Math.hypot(x2 - x1, y2 - y1);
    body = (
      <mesh position={[(x1 + x2) / 2, (y1 + y2) / 2, height / 2]} rotation={[0, 0, Math.atan2(y2 - y1, x2 - x1)]} {...events}>
        <boxGeometry args={[length, 0.05, height]} />{material}{edges}
      </mesh>
    );
    labelAt = [(x1 + x2) / 2, (y1 + y2) / 2, height];
  }
  return (
    <group>
      {body}
      {!faded && (
        <TextLabel text={`${o.label ?? (o.kind === "line" ? "wall" : o.kind)}${full ? " · full height" : ` · ${o.height_m?.toFixed(2)} m`}`}
                   position={[labelAt[0], labelAt[1], labelAt[2] + 0.08]} palette={palette} strong={mine} />
      )}
    </group>
  );
}

function ObstacleHandles({ obstacle: o, box, ceiling, palette, onChange }: {
  obstacle: Obstacle; box: Box; ceiling: number; palette: Palette; onChange: (next: Obstacle) => void;
}) {
  const height = o.height_m ?? ceiling;
  const mid = Math.max(0.05, height / 2);
  const setHeight = (z: number) => onChange({ ...o, height_m: cm(clamp(z, 0.05, 10)) });
  const d = dimensionsOf(o);
  const handles: ReactNode[] = [];
  if (d.kind === "rectangle") {
    const [[x1, y1], [x2, y2]] = o.points;
    const [xa, xb, ya, yb] = [Math.min(x1, x2), Math.max(x1, x2), Math.min(y1, y2), Math.max(y1, y2)];
    const sides: { side: "left" | "right" | "front" | "back"; at: [number, number]; axis: "x" | "y"; name: string }[] = [
      { side: "left", at: [xa, (ya + yb) / 2], axis: "x", name: "length" },
      { side: "right", at: [xb, (ya + yb) / 2], axis: "x", name: "length" },
      { side: "front", at: [(xa + xb) / 2, ya], axis: "y", name: "width" },
      { side: "back", at: [(xa + xb) / 2, yb], axis: "y", name: "width" },
    ];
    sides.forEach(({ side, at, axis, name }) => handles.push(
      <DragHandle palette={palette} key={side} position={[at[0], at[1], mid]} colour={palette.foreground} plane="floor" title={`Drag to change the ${name}`}
                  onDrag={(p) => onChange(resizeRectangle(o, side, axis === "x" ? p.x : p.y, box))} />,
    ));
    handles.push(
      <DragHandle palette={palette} key="top" position={[(xa + xb) / 2, (ya + yb) / 2, height]} colour={palette.primary} plane="vertical"
                  title="Drag to change the height" onDrag={(p) => setHeight(p.z)} />,
    );
  } else if (d.kind === "circle") {
    handles.push(
      <DragHandle palette={palette} key="r" position={[d.cx + d.radius, d.cy, mid]} colour={palette.foreground} plane="floor" title="Drag to change the diameter"
                  onDrag={(p) => onChange(obstacleFrom(o, { ...d, radius: Math.hypot(p.x - d.cx, p.y - d.cy) }, box))} />,
      <DragHandle palette={palette} key="top" position={[d.cx, d.cy, height]} colour={palette.primary} plane="vertical"
                  title="Drag to change the height" onDrag={(p) => setHeight(p.z)} />,
    );
  } else {
    handles.push(
      <DragHandle palette={palette} key="a" position={[d.x1, d.y1, mid]} colour={palette.foreground} plane="floor" title="Drag this end"
                  onDrag={(p) => onChange(obstacleFrom(o, { ...d, x1: p.x, y1: p.y }, box))} />,
      <DragHandle palette={palette} key="b" position={[d.x2, d.y2, mid]} colour={palette.foreground} plane="floor" title="Drag this end"
                  onDrag={(p) => onChange(obstacleFrom(o, { ...d, x2: p.x, y2: p.y }, box))} />,
      <DragHandle palette={palette} key="top" position={[(d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2, height]} colour={palette.primary} plane="vertical"
                  title="Drag to change the height" onDrag={(p) => setHeight(p.z)} />,
    );
  }
  return <group>{handles}</group>;
}

function FenceHandles({ fence, box, zMax, onFence, palette }: {
  fence: Geofence; box: Box; zMax: number; onFence: (fence: Geofence) => void; palette: Palette;
}) {
  const band = { z_min: fence.z_min, z_max: fence.z_max };
  const mid = (fence.z_min + fence.z_max) / 2;
  const handles: ReactNode[] = [];
  const setTop = (z: number) => onFence({ ...fence, z_max: cm(clamp(z, fence.z_min + 0.05, zMax)) });
  if (fence.shape === "rectangle") {
    const r = rectangleOf(fence);
    const [xa, xb, ya, yb] = [r.xMin, r.xMin + r.length, r.yMin, r.yMin + r.width];
    const rebuild = (nxa: number, nxb: number, nya: number, nyb: number) =>
      onFence(rectangleFence(nxa, nya, Math.max(MIN_SIZE_M, nxb - nxa), Math.max(MIN_SIZE_M, nyb - nya), band));
    handles.push(
      <DragHandle palette={palette} key="l" position={[xa, (ya + yb) / 2, mid]} colour={palette.foreground} plane="floor" title="Drag to change the length"
                  onDrag={(p) => rebuild(clamp(p.x, box.xMin, xb - MIN_SIZE_M), xb, ya, yb)} />,
      <DragHandle palette={palette} key="r" position={[xb, (ya + yb) / 2, mid]} colour={palette.foreground} plane="floor" title="Drag to change the length"
                  onDrag={(p) => rebuild(xa, clamp(p.x, xa + MIN_SIZE_M, box.xMax), ya, yb)} />,
      <DragHandle palette={palette} key="f" position={[(xa + xb) / 2, ya, mid]} colour={palette.foreground} plane="floor" title="Drag to change the width"
                  onDrag={(p) => rebuild(xa, xb, clamp(p.y, box.yMin, yb - MIN_SIZE_M), yb)} />,
      <DragHandle palette={palette} key="b" position={[(xa + xb) / 2, yb, mid]} colour={palette.foreground} plane="floor" title="Drag to change the width"
                  onDrag={(p) => rebuild(xa, xb, ya, clamp(p.y, ya + MIN_SIZE_M, box.yMax))} />,
      <DragHandle palette={palette} key="t" position={[(xa + xb) / 2, (ya + yb) / 2, fence.z_max]} colour={palette.primary} plane="vertical"
                  title="Drag to change the height" onDrag={(p) => setTop(p.z)} />,
    );
  } else if (fence.shape === "circle") {
    const c = circleOf(fence);
    handles.push(
      <DragHandle palette={palette} key="r" position={[c.cx + c.radius, c.cy, mid]} colour={palette.foreground} plane="floor" title="Drag to change the diameter"
                  onDrag={(p) => {
                    const most = Math.min(c.cx - box.xMin, box.xMax - c.cx, c.cy - box.yMin, box.yMax - c.cy);
                    onFence(circleFence(c.cx, c.cy, clamp(Math.hypot(p.x - c.cx, p.y - c.cy), MIN_SIZE_M, most), band));
                  }} />,
      <DragHandle palette={palette} key="t" position={[c.cx, c.cy, fence.z_max]} colour={palette.primary} plane="vertical"
                  title="Drag to change the height" onDrag={(p) => setTop(p.z)} />,
    );
  } else {
    fence.vertices.forEach(([x, y], index) => handles.push(
      <DragHandle palette={palette} key={`v${index}`} position={[x, y, fence.z_min]} colour={palette.foreground} plane="floor"
                  title={`Drag corner ${index + 1}`}
                  onDrag={(p) => onFence({ ...fence, vertices: fence.vertices.map((v, i) => (i === index
                    ? [cm(clamp(p.x, box.xMin, box.xMax)), cm(clamp(p.y, box.yMin, box.yMax))] as XY : v)) })} />,
    ));
    const [x0, y0] = fence.vertices[0];
    handles.push(
      <DragHandle palette={palette} key="t" position={[x0, y0, fence.z_max]} colour={palette.primary} plane="vertical"
                  title="Drag to change the height" onDrag={(p) => setTop(p.z)} />,
    );
  }
  return <group>{handles}</group>;
}

// ── dragging ─────────────────────────────────────────────────────────────

/**
 * A handle: a small sphere dragged along the floor (at its own height) or up
 * and down (in the vertical plane facing the camera). The orbit is paused
 * while it moves, so a drag never also turns the room.
 */
function DragHandle({ position, colour, plane, onDrag, title, palette }: {
  palette: Palette;
  position: [number, number, number];
  colour: string;
  plane: "floor" | "vertical";
  onDrag: (point: Vector3) => void;
  title: string;
}) {
  const { camera, controls, invalidate } = useThree();
  const [hover, setHover] = useState(false);
  const active = useRef<Plane | null>(null);
  const hit = useMemo(() => new Vector3(), []);
  const orbit = controls as unknown as OrbitControlsImpl | null;

  const down = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    const [x, y, z] = position;
    if (plane === "floor") {
      active.current = new Plane(new Vector3(0, 0, 1), -z);
    } else {
      const facing = camera.position.clone().sub(new Vector3(x, y, z));
      facing.z = 0;
      if (facing.lengthSq() < 1e-6) facing.set(0, -1, 0);
      facing.normalize();
      active.current = new Plane().setFromNormalAndCoplanarPoint(facing, new Vector3(x, y, z));
    }
    (e.target as unknown as Element).setPointerCapture?.(e.pointerId);
    if (orbit) orbit.enabled = false;
  };
  const move = (e: ThreeEvent<PointerEvent>) => {
    if (!active.current) return;
    e.stopPropagation();
    if (e.ray.intersectPlane(active.current, hit)) {
      onDrag(hit.clone());
      invalidate();
    }
  };
  const up = (e: ThreeEvent<PointerEvent>) => {
    if (!active.current) return;
    active.current = null;
    (e.target as unknown as Element).releasePointerCapture?.(e.pointerId);
    if (orbit) orbit.enabled = true;
  };
  return (
    <mesh position={position} onPointerDown={down} onPointerMove={move} onPointerUp={up}
          onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "grab"; }}
          onPointerOut={() => { setHover(false); document.body.style.cursor = ""; }}
          onClick={(e) => e.stopPropagation()}>
      <sphereGeometry args={[hover ? 0.06 : 0.045, 16, 12]} />
      <meshBasicMaterial color={colour} />
      {hover && (
        <TextLabel text={title} position={[0, 0, 0.12]} palette={palette} strong />
      )}
    </mesh>
  );
}

/** Dragging a whole selected thing across the floor: reports each step. */
function useFloorDrag(enabled: boolean, onStep: (dx: number, dy: number) => void) {
  const { controls, invalidate } = useThree();
  const last = useRef<Vector3 | null>(null);
  const plane = useMemo(() => new Plane(new Vector3(0, 0, 1), 0), []);
  const hit = useMemo(() => new Vector3(), []);
  const orbit = controls as unknown as OrbitControlsImpl | null;
  if (!enabled) return {};
  return {
    onPointerDown: (e: ThreeEvent<PointerEvent>) => {
      if (e.button !== 0) return;
      e.stopPropagation();
      if (!e.ray.intersectPlane(plane, hit)) return;
      last.current = hit.clone();
      (e.target as unknown as Element).setPointerCapture?.(e.pointerId);
      if (orbit) orbit.enabled = false;
    },
    onPointerMove: (e: ThreeEvent<PointerEvent>) => {
      if (!last.current) return;
      e.stopPropagation();
      if (!e.ray.intersectPlane(plane, hit)) return;
      onStep(hit.x - last.current.x, hit.y - last.current.y);
      last.current = hit.clone();
      invalidate();
    },
    onPointerUp: (e: ThreeEvent<PointerEvent>) => {
      if (!last.current) return;
      last.current = null;
      (e.target as unknown as Element).releasePointerCapture?.(e.pointerId);
      if (orbit) orbit.enabled = true;
    },
  };
}

// ── the path ─────────────────────────────────────────────────────────────

function PathLayer({ path, takeoffHeight, bad, palette, faded, progress, editing, box, current, select, moved }: {
  path: PathSource; takeoffHeight: number; bad: Set<string | null>; palette: Palette; faded: boolean;
  progress?: Record<string, PointState>; editing?: Edit3D; box: Box; current: Handle | null;
  select?: (handle: Handle | null) => void; moved: (e: { clientX: number; clientY: number }) => boolean;
}) {
  const legs = legsOf(path, takeoffHeight);
  const unflown = unflownIds(path);
  const lastStop = landsAt(path);
  const opacity = faded ? FADED : 1;
  const [hx, hy] = path.home;

  return (
    <group>
      {/* the start: a pad on the floor, and the climb to the takeoff height */}
      <StartPad at={path.home} palette={palette} opacity={opacity} bad={bad.has("home")}
                selected={sameHandle(current, { kind: "home" })}
                editing={editing} box={box} select={select} moved={moved} />
      <Line points={[[hx, hy, 0], [hx, hy, takeoffHeight]]} color={palette.foreground} lineWidth={1}
            dashed dashSize={0.04} gapSize={0.04} transparent opacity={0.6 * opacity} />

      {legs.map((leg, i) => {
        const wrong = bad.has(leg.name);
        const colour = wrong ? palette.critical : palette.foreground;
        const a = new Vector3(leg.a[0], leg.a[1], leg.za);
        const b = new Vector3(leg.b[0], leg.b[1], leg.zb);
        return (
          <group key={`${leg.name}-${i}`}>
            <Line points={[a, b]} color={colour} lineWidth={wrong ? 3 : 2} dashed dashSize={0.08} gapSize={0.05}
                  transparent opacity={(wrong ? 1 : 0.75) * opacity} />
            <LegArrow a={a} b={b} colour={colour} opacity={opacity} />
          </group>
        );
      })}

      {path.points.map((p) => (
        <PointMarker key={p.id} point={p} palette={palette} opacity={opacity}
                     wrong={bad.has(p.id)} skipped={unflown.has(p.id)} isEnd={p.id === lastStop}
                     state={progress?.[p.id]} selected={sameHandle(current, { kind: "point", id: p.id })}
                     editing={editing} box={box} select={select} moved={moved} />
      ))}
    </group>
  );
}

function LegArrow({ a, b, colour, opacity }: { a: Vector3; b: Vector3; colour: string; opacity: number }) {
  const direction = b.clone().sub(a);
  if (direction.length() < 0.2) return null;
  direction.normalize();
  const mid = a.clone().add(b).multiplyScalar(0.5);
  // A cone points along +y: turn +y onto the leg's direction.
  const turn = new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), direction);
  return (
    <mesh position={mid} quaternion={turn}>
      <coneGeometry args={[0.035, 0.09, 12]} />
      <meshBasicMaterial color={colour} transparent opacity={opacity} />
    </mesh>
  );
}

function PointMarker({ point: p, palette, opacity, wrong, skipped, isEnd, state, selected, editing, box, select, moved }: {
  point: InspectionPoint; palette: Palette; opacity: number; wrong: boolean; skipped: boolean; isEnd: boolean;
  state?: PointState; selected: boolean; editing?: Edit3D; box: Box;
  select?: (handle: Handle | null) => void; moved: (e: { clientX: number; clientY: number }) => boolean;
}) {
  const { controls, invalidate } = useThree();
  const orbit = controls as unknown as OrbitControlsImpl | null;
  const drag = useRef<Plane | null>(null);
  const hit = useMemo(() => new Vector3(), []);
  const colour = wrong ? palette.critical : state === "done" ? palette.good
    : state === "current" ? palette.warning : palette.primary;
  const alpha = (skipped ? 0.35 : 1) * opacity;
  return (
    <group>
      <Line points={[[p.x_m, p.y_m, 0], [p.x_m, p.y_m, p.z_m]]} color={colour} lineWidth={1}
            dashed dashSize={0.03} gapSize={0.03} transparent opacity={0.55 * alpha} />
      <mesh position={[p.x_m, p.y_m, 0.004]}>
        <ringGeometry args={[0.03, 0.05, 20]} />
        <meshBasicMaterial color={colour} transparent opacity={0.6 * alpha} />
      </mesh>
      <mesh
        position={[p.x_m, p.y_m, p.z_m]}
        onClick={(e) => { e.stopPropagation(); if (!moved(e.nativeEvent)) select?.({ kind: "point", id: p.id }); }}
        onContextMenu={(e) => {
          e.stopPropagation();
          e.nativeEvent.preventDefault();
          if (!editing?.onPointMenu) return;
          editing.onSelect({ kind: "point", id: p.id });
          editing.onPointMenu(p.id, { x: e.nativeEvent.clientX, y: e.nativeEvent.clientY });
        }}
        onPointerDown={editing ? (e) => {
          if (e.button !== 0) return;
          e.stopPropagation();
          // Along the floor at the point's height; with Shift, up and down.
          drag.current = e.shiftKey
            ? new Plane().setFromNormalAndCoplanarPoint(new Vector3(0, -1, 0), new Vector3(p.x_m, p.y_m, p.z_m))
            : new Plane(new Vector3(0, 0, 1), -p.z_m);
          (e.target as unknown as Element).setPointerCapture?.(e.pointerId);
          if (orbit) orbit.enabled = false;
          editing.onSelect({ kind: "point", id: p.id });
        } : undefined}
        onPointerMove={editing ? (e) => {
          if (!drag.current) return;
          e.stopPropagation();
          if (!e.ray.intersectPlane(drag.current, hit)) return;
          if (drag.current.normal.z === 1) {
            editing.onPoint(p.id, { x_m: cm(clamp(hit.x, box.xMin, box.xMax)), y_m: cm(clamp(hit.y, box.yMin, box.yMax)) });
          } else {
            editing.onPoint(p.id, { z_m: cm(clamp(hit.z, 0.05, editing.zMax)) });
          }
          invalidate();
        } : undefined}
        onPointerUp={editing ? (e) => {
          if (!drag.current) return;
          drag.current = null;
          (e.target as unknown as Element).releasePointerCapture?.(e.pointerId);
          if (orbit) orbit.enabled = true;
        } : undefined}
      >
        <sphereGeometry args={[selected ? 0.065 : 0.05, 20, 14]} />
        <meshStandardMaterial color={skipped ? palette.surface : colour} transparent opacity={alpha}
                              emissive={selected ? colour : "#000000"} emissiveIntensity={selected ? 0.4 : 0} />
      </mesh>
      {isEnd && (
        <mesh position={[p.x_m, p.y_m, p.z_m]} rotation={[0, 0, 0]}>
          <torusGeometry args={[0.1, 0.012, 8, 32]} />
          <meshBasicMaterial color={palette.foreground} transparent opacity={alpha} />
        </mesh>
      )}
      <TextLabel text={`${p.id} · ${p.z_m.toFixed(2)} m${isEnd ? " · END" : ""}${skipped ? " · not flown" : ""}${wrong ? " !" : ""}`}
                 position={[p.x_m, p.y_m, p.z_m + 0.1]} palette={palette} strong={selected || isEnd}
                 opacity={Math.max(alpha, 0.35)} />
    </group>
  );
}

function StartPad({ at, palette, opacity, bad, selected, editing, box, select, moved }: {
  at: XY; palette: Palette; opacity: number; bad: boolean; selected: boolean; editing?: Edit3D; box: Box;
  select?: (handle: Handle | null) => void; moved: (e: { clientX: number; clientY: number }) => boolean;
}) {
  const drag = useFloorDrag(!!editing && selected, (dx, dy) =>
    editing?.onHome([cm(clamp(at[0] + dx, box.xMin, box.xMax)), cm(clamp(at[1] + dy, box.yMin, box.yMax))]));
  return (
    <group>
      <mesh position={[at[0], at[1], 0.01]}
            onClick={(e) => { e.stopPropagation(); if (!moved(e.nativeEvent)) select?.({ kind: "home" }); }} {...drag}>
        <boxGeometry args={[0.16, 0.16, 0.02]} />
        <meshStandardMaterial color={palette.surface} transparent opacity={opacity} />
        <Edges color={bad ? palette.critical : palette.foreground} lineWidth={selected ? 3 : 1.5} />
      </mesh>
      <TextLabel text="S" position={[at[0], at[1], 0.09]} palette={palette} strong opacity={Math.max(opacity, 0.35)} />
    </group>
  );
}

// ── the drone ────────────────────────────────────────────────────────────

/** The Crazyflie, roughly to scale (1.5×): a body, four arms, four rotors, a
 *  green ring on the floor under it, and a "D" that always faces the camera. */
function Drone({ at, height, yaw, palette }: { at: XY; height: number; yaw: number; palette: Palette; box: Box }) {
  const arm = 0.046 * DRONE_SCALE;
  const z = Math.max(0.02, height);
  return (
    <group>
      <mesh position={[at[0], at[1], 0.005]}>
        <ringGeometry args={[0.09, 0.12, 32]} />
        <meshBasicMaterial color={palette.good} />
      </mesh>
      {height > 0.03 && (
        <Line points={[[at[0], at[1], 0], [at[0], at[1], z]]} color={palette.good} lineWidth={1} dashed dashSize={0.03} gapSize={0.03} />
      )}
      <group position={[at[0], at[1], z]} rotation={[0, 0, (yaw * Math.PI) / 180]}>
        <mesh>
          <boxGeometry args={[0.04 * DRONE_SCALE, 0.04 * DRONE_SCALE, 0.012 * DRONE_SCALE]} />
          <meshStandardMaterial color={palette.foreground} />
        </mesh>
        {[45, 135, 225, 315].map((deg) => {
          const r = (deg * Math.PI) / 180;
          return (
            <group key={deg}>
              <mesh position={[Math.cos(r) * arm / 2, Math.sin(r) * arm / 2, 0]} rotation={[0, 0, r]}>
                <boxGeometry args={[arm, 0.006 * DRONE_SCALE, 0.004 * DRONE_SCALE]} />
                <meshStandardMaterial color={palette.foreground} />
              </mesh>
              <mesh position={[Math.cos(r) * arm, Math.sin(r) * arm, 0.006]} rotation={[Math.PI / 2, 0, 0]}>
                <cylinderGeometry args={[0.022 * DRONE_SCALE, 0.022 * DRONE_SCALE, 0.002, 20]} />
                <meshStandardMaterial color={palette.good} transparent opacity={0.7} />
              </mesh>
            </group>
          );
        })}
        {/* the nose: which way it is facing */}
        <mesh position={[0.03 * DRONE_SCALE, 0, 0.008]}>
          <sphereGeometry args={[0.008 * DRONE_SCALE, 10, 8]} />
          <meshBasicMaterial color={palette.critical} />
        </mesh>
      </group>
      <TextLabel text="D" position={[at[0], at[1], z + 0.12]} palette={palette} ring={palette.good} />
    </group>
  );
}

// ── labels ───────────────────────────────────────────────────────────────

/**
 * A label that always faces the camera and stays the same size on screen: a
 * sprite drawn from a small canvas in the theme's own colours. Not drei's
 * <Html> — that mounts a React root per label (a dozen here) and React 19
 * warns about unmounting them mid-render — and not <Text>, which downloads
 * a font the window's content policy would refuse.
 */
function TextLabel({ text, position, palette, strong = false, quiet = false, ring, opacity = 1 }: {
  text: string;
  position: [number, number, number];
  palette: Palette;
  strong?: boolean;
  quiet?: boolean;
  /** Draw it as a round badge ringed in this colour — the drone's D. */
  ring?: string;
  opacity?: number;
}) {
  const { texture, aspect } = useMemo(() => {
    const scale = 2;                                     // crisp on a 2× display
    const font = `${strong || ring ? 700 : 600} ${22 * scale}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    const probe = document.createElement("canvas").getContext("2d");
    if (probe) probe.font = font;
    const textWidth = Math.ceil(probe?.measureText(text).width ?? text.length * 12 * scale);
    const height = 34 * scale;
    const width = ring ? height : textWidth + 16 * scale;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      if (ring) {
        ctx.beginPath();
        ctx.arc(width / 2, height / 2, height / 2 - 3 * scale, 0, Math.PI * 2);
        ctx.fillStyle = palette.surface;
        ctx.fill();
        ctx.lineWidth = 4 * scale;
        ctx.strokeStyle = ring;
        ctx.stroke();
      } else if (!quiet) {
        ctx.fillStyle = palette.surface;
        ctx.fillRect(0, 0, width, height);
        ctx.lineWidth = (strong ? 3 : 1.5) * scale;
        ctx.strokeStyle = strong ? palette.foreground : palette.muted;
        ctx.strokeRect(1, 1, width - 2, height - 2);
      }
      ctx.fillStyle = quiet ? palette.muted : palette.foreground;
      ctx.fillText(text, width / 2, height / 2 + scale);
    }
    const made = new CanvasTexture(canvas);
    made.colorSpace = SRGBColorSpace;
    return { texture: made, aspect: width / height };
  }, [text, strong, quiet, ring, palette.surface, palette.foreground, palette.muted]);
  useEffect(() => () => texture.dispose(), [texture]);
  const h = ring ? 0.05 : 0.036;
  return (
    <sprite position={position} scale={[h * aspect, h, 1]} renderOrder={10}>
      <spriteMaterial map={texture} transparent opacity={opacity} depthTest={false} sizeAttenuation={false} />
    </sprite>
  );
}
