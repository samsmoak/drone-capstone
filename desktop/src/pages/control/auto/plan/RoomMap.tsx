/**
 * The room map, in 2-D or 3-D — one switch, the same room, the same selection.
 *
 *   2D   PlanCanvas: the plan from above, exact, drag handles in metres
 *   3D   Room3D: the room's flying space, obstacles at their height, the path
 *        at its heights and the drone; orbit, pick, drag sides and tops
 *
 * Everywhere Auto draws a room — ① the mission, ① the editor, ③ Fly — it draws
 * it through here, so the switch is always in the same place and the choice
 * (remembered per machine) carries across them. V toggles it while the map has
 * focus. The selection belongs to the page, not the view: switching keeps it.
 *
 * 3-D IS LOADED ON FIRST USE (React.lazy): three.js stays out of the window's
 * start-up. If this machine cannot draw WebGL — some Linux GPU setups — the
 * map stays in 2-D and says why, rather than showing an empty box.
 */

import { lazy, Suspense, useState, type ReactNode } from "react";
import type { Geofence, InspectionPoint, Obstacle, OuterBound, Problem, XY } from "@/lib/agent";
import { Spinner } from "@/components/ui";
import { SmallButton } from "./fields";
import { PlanCanvas, type Editing, type Handle, type PointState } from "./PlanCanvas";
import type { CameraPreset, Edit3D } from "./Room3D";
import { webglAvailable } from "./webgl";
import type { PathSource } from "./path";

const Room3D = lazy(() => import("./Room3D"));

export type MapView = "2d" | "3d";
const VIEW_KEY = "cropwatcher.auto.mapView";

function rememberedView(): MapView {
  try { return localStorage.getItem(VIEW_KEY) === "2d" ? "2d" : "3d"; } catch { return "3d"; }
}

/** Everything the editor can change from the map, in either view. */
export type MapEditing = Editing & Omit<Edit3D, keyof Editing | "onSelect" | "selected" | "placing" | "onPlace" | "onPointMenu">;

export function RoomMap({
  outer, fence, obstacles, path, takeoffHeight = 0.4, problems = [], drone = null, droneHeight, droneYaw,
  progress, editing, label, overlay, heightClass = "h-[clamp(18rem,52vh,34rem)]",
}: {
  outer: OuterBound;
  fence: Geofence | null;
  obstacles: Obstacle[];
  path: PathSource | null;
  takeoffHeight?: number;
  problems?: Problem[];
  drone?: XY | null;
  droneHeight?: number | null;
  droneYaw?: number | null;
  progress?: Record<string, PointState>;
  editing?: MapEditing;
  label: string;
  /** Drawn over the map's lower-left corner: the selected object's numbers. */
  overlay?: ReactNode;
  /** The map's height; "h-full" in full screen. */
  heightClass?: string;
}) {
  const canDraw3d = webglAvailable();
  const [view, setView] = useState<MapView>(() => (canDraw3d ? rememberedView() : "2d"));
  const [camera, setCamera] = useState<{ preset: CameraPreset; n: number }>({ preset: "three-quarter", n: 0 });
  // Not editing, a click still picks a thing to look at.
  const [looking, setLooking] = useState<Handle | null>(null);

  const choose = (next: MapView) => {
    setView(next);
    try { localStorage.setItem(VIEW_KEY, next); } catch { /* a private window */ }
  };
  const shown: MapView = canDraw3d ? view : "2d";
  const aim = (preset: CameraPreset) => setCamera((c) => ({ preset, n: c.n + 1 }));

  return (
    <div
      className="grid gap-0"
      onKeyDown={(e) => {
        const typing = (e.target as HTMLElement).closest("input, textarea, select");
        if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.key === "v" || e.key === "V") {
          e.preventDefault();
          if (canDraw3d) choose(shown === "3d" ? "2d" : "3d");
        }
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border border-b-0 border-[var(--border)] bg-[var(--surface)] px-2 py-1.5">
        <div className="flex items-center gap-1" role="group" aria-label="Room map view">
          <SmallButton pressed={shown === "2d"} onClick={() => choose("2d")} title="From above, to scale (V)">2D</SmallButton>
          <SmallButton pressed={shown === "3d"} disabled={!canDraw3d} onClick={() => choose("3d")}
                       title={canDraw3d ? "Orbit the room (V)" : "This computer cannot draw 3-D (no WebGL)."}>
            3D
          </SmallButton>
        </div>
        {shown === "3d" && (
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Camera">
            {([["three-quarter", "3/4"], ["top", "Top"], ["front", "Front"], ["side", "Side"], ["fit", "Fit room"]] as const).map(([preset, name]) => (
              <SmallButton key={preset} onClick={() => aim(preset)}>{name}</SmallButton>
            ))}
          </div>
        )}
      </div>

      <div className={`relative min-h-0 border border-[var(--border)] ${heightClass}`}>
        {shown === "2d" ? (
          <PlanCanvas
            outer={outer} fence={fence} obstacles={obstacles} path={path} takeoffHeight={takeoffHeight}
            problems={problems} drone={drone} progress={progress} label={label}
            editing={editing} selected={editing ? undefined : looking}
            className="block h-full w-full touch-none select-none bg-[var(--surface-2)]"
          />
        ) : (
          <Suspense fallback={<div className="grid h-full place-items-center"><Spinner label="Loading the 3-D view…" /></div>}>
            <Room3D
              outer={outer} fence={fence} obstacles={obstacles} path={path} takeoffHeight={takeoffHeight}
              problems={problems} drone={drone} droneHeight={droneHeight} droneYaw={droneYaw}
              progress={progress} camera={camera} label={label}
              editing={editing ? {
                selected: editing.selected, onSelect: editing.onSelect, onFence: editing.onFence,
                onObstacle: editing.onObstacle, onPoint: editing.onPoint, onHome: editing.onHome,
                onPlace: editing.onPlace, placing: editing.placing, onPointMenu: editing.onPointMenu,
                zMax: editing.zMax,
              } : undefined}
              selected={editing ? undefined : looking}
              onSelect={editing ? undefined : setLooking}
            />
          </Suspense>
        )}
        {overlay && (
          <div className="pointer-events-none absolute inset-x-2 bottom-2 flex justify-start">
            <div className="pointer-events-auto max-h-[70%] max-w-full overflow-auto border border-[var(--border)] bg-[var(--surface)] shadow-sm">
              {overlay}
            </div>
          </div>
        )}
      </div>

      <p className="pt-1.5 text-xs leading-relaxed text-[var(--muted)]">
        {shown === "3d"
          ? "Drag to turn the room, scroll to zoom, right-drag to pan. Double-click anything to swing round it. Click the room's walls or an obstacle to select it."
          : canDraw3d ? "From above, to scale. The bottom edge is the front. Heights are above the floor where the drone takes off."
          : "From above, to scale. This computer cannot draw the 3-D view (WebGL is unavailable), so the map stays in 2-D."}
      </p>
    </div>
  );
}

export type { Handle, PointState };
export type PointChange = Partial<InspectionPoint>;
