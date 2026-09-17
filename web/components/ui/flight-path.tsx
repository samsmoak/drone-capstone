import type { TelemetryRow, ZoneRow } from "@/lib/queries";

/**
 * The drone's track over the greenhouse floor, top-down. Plain SVG.
 *
 * Equal scale on both axes, always. A path drawn with independent x and y
 * scales turns a square lawnmower pattern into a rectangle and makes a
 * drift along one axis look larger than the same drift along the other.
 *
 * Zones are drawn behind the track, so "did it cover zone B" is answered by
 * looking rather than by cross-referencing coordinates.
 */

const SIZE = 480;
const PAD = 36;

type Point = { x: number; y: number };

function niceTicks(min: number, max: number, count = 5): number[] {
  const span = max - min || 1;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const err = (count * step) / span;
  const nice = step * (err <= 0.15 ? 10 : err <= 0.35 ? 5 : err <= 0.75 ? 2 : 1);
  const ticks: number[] = [];
  for (let t = Math.ceil(min / nice) * nice; t <= max + 1e-9; t += nice) {
    ticks.push(Math.round(t * 1000) / 1000);
  }
  return ticks;
}

export function FlightPath({
  rows,
  zones,
}: {
  rows: TelemetryRow[];
  zones: ZoneRow[];
}) {
  const points: Point[] = rows
    .filter((r) => r.x_m != null && r.y_m != null)
    .map((r) => ({ x: r.x_m!, y: r.y_m! }));

  if (points.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
        No position readings in this flight, so there is no path to draw. Position
        comes from the Lighthouse deck — if every flight shows this, check that
        both base stations are powered and visible to the drone.
      </p>
    );
  }

  // One square extent covering the path and every zone, so both axes share a
  // scale and nothing is clipped.
  const xs = [...points.map((p) => p.x), ...zones.flatMap((z) => [z.x_min, z.x_max])];
  const ys = [...points.map((p) => p.y), ...zones.flatMap((z) => [z.y_min, z.y_max])];
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const half =
    Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 0.5) / 2 * 1.1;
  const [x0, x1, y0, y1] = [cx - half, cx + half, cy - half, cy + half];

  const inner = SIZE - PAD * 2;
  const sx = (x: number) => PAD + ((x - x0) / (x1 - x0)) * inner;
  // SVG y grows downward; the floor plan's y grows upward.
  const sy = (y: number) => PAD + (1 - (y - y0) / (y1 - y0)) * inner;

  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`)
    .join(" ");
  const start = points[0];
  const end = points[points.length - 1];

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="h-auto w-full max-w-[480px]"
        role="img"
        aria-label={`Flight path, top-down. ${points.length} positions, from (${start.x.toFixed(2)}, ${start.y.toFixed(2)}) to (${end.x.toFixed(2)}, ${end.y.toFixed(2)}) metres.`}
      >
        {/* Grid */}
        {niceTicks(x0, x1).map((t) => (
          <g key={`x${t}`}>
            <line x1={sx(t)} x2={sx(t)} y1={PAD} y2={SIZE - PAD} stroke="var(--grid)" />
            <text x={sx(t)} y={SIZE - PAD + 16} textAnchor="middle" fontSize="11" fill="var(--muted)">
              {t}
            </text>
          </g>
        ))}
        {niceTicks(y0, y1).map((t) => (
          <g key={`y${t}`}>
            <line x1={PAD} x2={SIZE - PAD} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" />
            <text x={PAD - 6} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
              {t}
            </text>
          </g>
        ))}
        <text x={SIZE / 2} y={SIZE - 4} textAnchor="middle" fontSize="11" fill="var(--muted)">
          x (m)
        </text>
        <text x={10} y={PAD - 12} fontSize="11" fill="var(--muted)">
          y (m)
        </text>

        {/* Zones, behind the track */}
        {zones.map((z) => (
          <g key={z.id}>
            <title>{`Zone ${z.label}`}</title>
            <rect
              x={sx(z.x_min)}
              y={sy(z.y_max)}
              width={sx(z.x_max) - sx(z.x_min)}
              height={sy(z.y_min) - sy(z.y_max)}
              fill="none"
              stroke="var(--border)"
              strokeWidth={1.5}
            />
            <text x={sx(z.x_min) + 4} y={sy(z.y_max) + 13} fontSize="11" fill="var(--muted)">
              {z.label}
            </text>
          </g>
        ))}

        <path d={d} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />

        {/* Start and end are labelled in words; shape differs too, so neither
            depends on colour. The surface ring keeps them legible on the path. */}
        <g>
          <title>{`Start (${start.x.toFixed(2)}, ${start.y.toFixed(2)}) m`}</title>
          <circle cx={sx(start.x)} cy={sy(start.y)} r={6} fill="var(--surface)" stroke="var(--foreground)" strokeWidth={2} />
          <text x={sx(start.x) + 10} y={sy(start.y) - 8} fontSize="12" fill="var(--foreground)">
            Start
          </text>
        </g>
        <g>
          <title>{`End (${end.x.toFixed(2)}, ${end.y.toFixed(2)}) m`}</title>
          <rect x={sx(end.x) - 6} y={sy(end.y) - 6} width={12} height={12} fill="var(--foreground)" stroke="var(--surface)" strokeWidth={2} />
          <text x={sx(end.x) + 10} y={sy(end.y) + 16} fontSize="12" fill="var(--foreground)">
            End
          </text>
        </g>
      </svg>
      <figcaption className="mt-2 text-xs text-[var(--muted)]">
        Top-down, equal scale on both axes. Coordinates are Lighthouse metres.
      </figcaption>
    </figure>
  );
}
