/**
 * The numbers of each thing in a room, in the editor's words — used in the
 * form beside the map AND in the panel over the map for whatever is selected,
 * so the two can never describe the same object differently.
 *
 *   LENGTH left→right · WIDTH front→back · HEIGHT up from the floor
 *   FROM LEFT / FROM FRONT: from the room map's front-left corner
 *
 * (geometry.ts, "the words"). Every value is clamped to the room's map on
 * commit, and the field shows what was kept.
 */

import { useId } from "react";
import type { Geofence, InspectionPoint, Obstacle, PlanLimits, XY } from "@/lib/agent";
import { formatMetres } from "@/lib/format";
import { NumberField, SmallButton } from "./fields";
import {
  circleFence, circleOf, clamp, cm, dimensionsOf, fromPlace, lengthOf, MIN_SIZE_M, obstacleFrom,
  placeOf, rectangleFence, rectangleOf, type Box, type ObstacleDimensions,
} from "./geometry";

// ── the room (geofence) ──────────────────────────────────────────────────

export function FenceFields({ fence, box, limits, setFence, compact = false }: {
  fence: Geofence;
  box: Box;
  limits: PlanLimits;
  setFence: (fence: Geofence) => void;
  /** Over the map: the shape's numbers only, no corner list. */
  compact?: boolean;
}) {
  const band = { z_min: fence.z_min, z_max: fence.z_max };
  const mapL = cm(box.xMax - box.xMin);
  const mapW = cm(box.yMax - box.yMin);
  const rect = rectangleOf(fence);
  const circle = circleOf(fence);
  const [left, front] = placeOf([rect.xMin, rect.yMin], box);
  const [cLeft, cFront] = placeOf([circle.cx, circle.cy], box);

  return (
    <div className="grid gap-2">
      {fence.shape === "rectangle" && (
        <div className="flex flex-wrap gap-3">
          <NumberField label="Length" value={rect.length} min={MIN_SIZE_M} max={cm(mapL - left)}
                       onCommit={(v) => setFence(rectangleFence(rect.xMin, rect.yMin, v, rect.width, band))} />
          <NumberField label="Width" value={rect.width} min={MIN_SIZE_M} max={cm(mapW - front)}
                       onCommit={(v) => setFence(rectangleFence(rect.xMin, rect.yMin, rect.length, v, band))} />
          <NumberField label="From left" value={left} min={0} max={cm(mapL - MIN_SIZE_M)}
                       onCommit={(v) => setFence(rectangleFence(box.xMin + v, rect.yMin, Math.min(rect.length, mapL - v), rect.width, band))} />
          <NumberField label="From front" value={front} min={0} max={cm(mapW - MIN_SIZE_M)}
                       onCommit={(v) => setFence(rectangleFence(rect.xMin, box.yMin + v, rect.length, Math.min(rect.width, mapW - v), band))} />
        </div>
      )}

      {fence.shape === "circle" && (
        <div className="flex flex-wrap gap-3">
          <NumberField label="Diameter" value={cm(circle.radius * 2)} min={MIN_SIZE_M * 2}
                       max={cm(2 * Math.min(circle.cx - box.xMin, box.xMax - circle.cx, circle.cy - box.yMin, box.yMax - circle.cy))}
                       onCommit={(v) => setFence(circleFence(circle.cx, circle.cy, v / 2, band))} />
          <NumberField label="Centre from left" value={cLeft} min={circle.radius} max={cm(mapL - circle.radius)}
                       onCommit={(v) => setFence(circleFence(box.xMin + v, circle.cy, circle.radius, band))} />
          <NumberField label="Centre from front" value={cFront} min={circle.radius} max={cm(mapW - circle.radius)}
                       onCommit={(v) => setFence(circleFence(circle.cx, box.yMin + v, circle.radius, band))} />
        </div>
      )}

      {fence.shape === "polygon" && !compact && (
        <ol className="grid gap-1.5">
          {fence.vertices.map((v, index) => {
            const [l, f] = placeOf(v, box);
            const set = (next: XY) => setFence({ ...fence, vertices: fence.vertices.map((p, i) => (i === index ? next : p)) });
            return (
              <li key={index} className="flex flex-wrap items-end gap-2">
                <span className="mono w-14 pb-2 text-xs">Corner {index + 1}</span>
                <NumberField label="From left" value={l} min={0} max={mapL} hint="" onCommit={(x) => set(fromPlace([x, f], box))} />
                <NumberField label="From front" value={f} min={0} max={mapW} hint="" onCommit={(y) => set(fromPlace([l, y], box))} />
                <SmallButton tone="danger" disabled={fence.vertices.length <= 3}
                             title={fence.vertices.length <= 3 ? "A geofence needs at least 3 corners to enclose anything." : undefined}
                             onClick={() => setFence({ ...fence, vertices: fence.vertices.filter((_, i) => i !== index) })}>
                  Remove
                </SmallButton>
              </li>
            );
          })}
        </ol>
      )}
      {fence.shape === "polygon" && compact && (
        <p className="text-xs text-[var(--muted)]">{fence.vertices.length} corners — drag them on the map, or set each in the form.</p>
      )}

      <div className="flex flex-wrap gap-3">
        <NumberField label="Height" value={fence.z_max} min={fence.z_min + 0.05} max={limits.z_max_m}
                     hint={`At most ${limits.z_max_m.toFixed(2)} m — the flight system's ceiling`}
                     onCommit={(v) => setFence({ ...fence, z_max: cm(v) })} />
        <NumberField label="Lowest flying height" value={fence.z_min} min={0.05} max={fence.z_max - 0.05}
                     hint="Nothing is flown lower"
                     onCommit={(v) => setFence({ ...fence, z_min: cm(v) })} />
      </div>
    </div>
  );
}

// ── obstacles ────────────────────────────────────────────────────────────

/** An obstacle's height: a number, or floor to ceiling (no height given). */
export function HeightField({ value, onChange }: { value: number | null | undefined; onChange: (v: number | null) => void }) {
  const id = useId();
  const full = value === null || value === undefined;
  return (
    <div className="grid content-start gap-1 text-xs">
      {full ? (
        <>
          <span className="eyebrow">Height</span>
          <span className="flex min-h-9 items-center text-sm">Floor to ceiling</span>
        </>
      ) : (
        <NumberField label="Height" value={value} min={0.05} max={10} hint={formatMetres(value)}
                     onCommit={(v) => onChange(cm(v))} />
      )}
      <label htmlFor={id} className="flex items-center gap-1.5">
        <input id={id} type="checkbox" className="h-4 w-4" checked={full}
               onChange={(e) => onChange(e.target.checked ? null : 0.75)} />
        <span>Floor to ceiling</span>
      </label>
    </div>
  );
}

export function ObstacleFields({ obstacle, box, onChange }: {
  obstacle: Obstacle;
  box: Box;
  onChange: (next: Obstacle) => void;
}) {
  const d = dimensionsOf(obstacle);
  const mapL = cm(box.xMax - box.xMin);
  const mapW = cm(box.yMax - box.yMin);
  const set = (change: Partial<ObstacleDimensions>) =>
    onChange(obstacleFrom(obstacle, { ...d, ...change } as ObstacleDimensions, box));
  const height = <HeightField value={obstacle.height_m} onChange={(h) => onChange({ ...obstacle, height_m: h })} />;

  if (d.kind === "rectangle") {
    const [left, front] = placeOf([d.cx - d.length / 2, d.cy - d.width / 2], box);
    return (
      <div className="flex flex-wrap gap-2">
        <NumberField label="Length" value={d.length} min={MIN_SIZE_M} max={mapL}
                     onCommit={(v) => set({ length: v, cx: box.xMin + left + v / 2 })} />
        <NumberField label="Width" value={d.width} min={MIN_SIZE_M} max={mapW}
                     onCommit={(v) => set({ width: v, cy: box.yMin + front + v / 2 })} />
        {height}
        <NumberField label="From left" value={left} min={0} max={cm(mapL - d.length)} hint=""
                     onCommit={(v) => set({ cx: box.xMin + v + d.length / 2 })} />
        <NumberField label="From front" value={front} min={0} max={cm(mapW - d.width)} hint=""
                     onCommit={(v) => set({ cy: box.yMin + v + d.width / 2 })} />
      </div>
    );
  }
  if (d.kind === "circle") {
    const [left, front] = placeOf([d.cx, d.cy], box);
    return (
      <div className="flex flex-wrap gap-2">
        <NumberField label="Diameter" value={cm(d.radius * 2)} min={MIN_SIZE_M}
                     max={cm(Math.min(mapL, mapW))} onCommit={(v) => set({ radius: v / 2 })} />
        {height}
        <NumberField label="Centre from left" value={left} min={0} max={mapL} hint=""
                     onCommit={(v) => set({ cx: box.xMin + v })} />
        <NumberField label="Centre from front" value={front} min={0} max={mapW} hint=""
                     onCommit={(v) => set({ cy: box.yMin + v })} />
      </div>
    );
  }
  const [l1, f1] = placeOf([d.x1, d.y1], box);
  const [l2, f2] = placeOf([d.x2, d.y2], box);
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        <NumberField label="Start from left" value={l1} min={0} max={mapL} hint="" onCommit={(v) => set({ x1: box.xMin + v })} />
        <NumberField label="Start from front" value={f1} min={0} max={mapW} hint="" onCommit={(v) => set({ y1: box.yMin + v })} />
        <NumberField label="End from left" value={l2} min={0} max={mapL} hint="" onCommit={(v) => set({ x2: box.xMin + v })} />
        <NumberField label="End from front" value={f2} min={0} max={mapW} hint="" onCommit={(v) => set({ y2: box.yMin + v })} />
        {height}
      </div>
      <p className="text-xs text-[var(--muted)]">Length {formatMetres(lengthOf([d.x1, d.y1], [d.x2, d.y2]))}</p>
    </div>
  );
}

// ── inspection points ────────────────────────────────────────────────────

export function PointFields({ point: p, box, band, minHold, setPoint }: {
  point: InspectionPoint;
  box: Box;
  band: { lo: number; hi: number };
  minHold: number;
  setPoint: (change: Partial<InspectionPoint>) => void;
}) {
  const [left, front] = placeOf([p.x_m, p.y_m], box);
  return (
    <div className="flex flex-wrap gap-2">
      <NumberField label="From left" value={left} min={0} max={cm(box.xMax - box.xMin)} hint=""
                   onCommit={(v) => setPoint({ x_m: cm(box.xMin + v) })} />
      <NumberField label="From front" value={front} min={0} max={cm(box.yMax - box.yMin)} hint=""
                   onCommit={(v) => setPoint({ y_m: cm(box.yMin + v) })} />
      <NumberField label="Height" value={p.z_m} min={band.lo} max={band.hi} hint=""
                   onCommit={(v) => setPoint({ z_m: cm(clamp(v, band.lo, band.hi)) })} />
      <NumberField label="Hold" unit="s" step={1} value={p.hold_s} min={minHold} max={300}
                   hint={`At least ${minHold} s`} onCommit={(v) => setPoint({ hold_s: Math.round(v * 10) / 10 })} />
    </div>
  );
}
