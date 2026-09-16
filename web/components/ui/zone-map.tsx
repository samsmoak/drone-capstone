import type { PredictionRow, ZoneRow } from "@/lib/queries";

/**
 * The greenhouse, top-down, each zone shaded by its latest health estimate.
 * Plain SVG rectangles.
 *
 * Magnitude, so a sequential ramp: one hue, light → dark, never a rainbow and
 * never the status colours. Status colours mean "act on this"; a health score
 * is a measurement, and the operator decides what counts as bad.
 *
 * The light end of the ramp sits close to the surface, so no cell relies on its
 * fill to be read. Every cell carries its label and figure on a surface chip,
 * which keeps text contrast independent of the step and the theme.
 */

/**
 * ASSUMPTION: `health_score` is 0–1, higher is healthier.
 *
 * Nothing in the schema or the agent defines its range yet — the model that
 * writes it is not wired in. The figure is always printed beside the colour, so
 * if the model emits another range the mismatch is visible, not silent. Pin
 * this when inference lands.
 */
const SCORE_MIN = 0;
const SCORE_MAX = 1;

export const HEALTH_STEPS = [
  { token: "--seq-100", label: "0.0–0.2" },
  { token: "--seq-250", label: "0.2–0.4" },
  { token: "--seq-400", label: "0.4–0.6" },
  { token: "--seq-550", label: "0.6–0.8" },
  { token: "--seq-700", label: "0.8–1.0" },
] as const;

function stepFor(score: number): (typeof HEALTH_STEPS)[number] {
  const t = (Math.min(SCORE_MAX, Math.max(SCORE_MIN, score)) - SCORE_MIN) / (SCORE_MAX - SCORE_MIN);
  return HEALTH_STEPS[Math.min(HEALTH_STEPS.length - 1, Math.floor(t * HEALTH_STEPS.length))];
}

const SIZE_W = 720;
const PAD = 8;
const GAP = 2; // surface gap between adjacent fills

export function ZoneMap({
  zones,
  health,
}: {
  zones: ZoneRow[];
  health: Map<string, PredictionRow>;
}) {
  const x0 = Math.min(...zones.map((z) => z.x_min));
  const x1 = Math.max(...zones.map((z) => z.x_max));
  const y0 = Math.min(...zones.map((z) => z.y_min));
  const y1 = Math.max(...zones.map((z) => z.y_max));

  // Equal scale: a 1 × 1 m zone is square on screen.
  const scale = (SIZE_W - PAD * 2) / (x1 - x0);
  const height = (y1 - y0) * scale + PAD * 2;
  const sx = (x: number) => PAD + (x - x0) * scale;
  const sy = (y: number) => PAD + (y1 - y) * scale; // floor-plan y grows upward

  return (
    <svg
      viewBox={`0 0 ${SIZE_W} ${height}`}
      className="h-auto w-full min-w-[560px]"
      role="img"
      aria-label="Zone health map. The same figures are listed in the table below."
    >
      {zones.map((z) => {
        const prediction = health.get(z.id);
        const score = prediction?.health_score ?? null;
        const x = sx(z.x_min) + GAP / 2;
        const y = sy(z.y_max) + GAP / 2;
        const w = sx(z.x_max) - sx(z.x_min) - GAP;
        const h = sy(z.y_min) - sy(z.y_max) - GAP;

        return (
          <g key={z.id}>
            <title>
              {score == null
                ? `Zone ${z.label}: no estimate yet`
                : `Zone ${z.label}: health ${score.toFixed(2)}${
                    prediction?.label ? ` (${prediction.label})` : ""
                  }`}
            </title>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              rx={4}
              fill={score == null ? "var(--surface)" : `var(${stepFor(score).token})`}
              stroke={score == null ? "var(--border)" : "none"}
              strokeDasharray={score == null ? "6 4" : undefined}
              strokeWidth={1.5}
            />
            <rect x={x + 8} y={y + 8} width={Math.min(w - 16, 112)} height={40} rx={6} fill="var(--surface)" />
            <text x={x + 16} y={y + 24} fontSize={12} fontWeight={600} fill="var(--foreground)">
              {z.label}
            </text>
            <text x={x + 16} y={y + 40} fontSize={12} fill="var(--foreground)" className="tabular">
              {score == null ? "No estimate" : score.toFixed(2)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function ZoneLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
      <span className="text-[var(--muted)]">Health score</span>
      <ul className="flex flex-wrap items-center gap-3">
        {HEALTH_STEPS.map((step) => (
          <li key={step.token} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-3 w-5 rounded-sm"
              style={{ background: `var(${step.token})` }}
            />
            <span className="tabular">{step.label}</span>
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-5 rounded-sm border border-dashed border-[var(--muted)]"
          />
          <span>No estimate</span>
        </li>
      </ul>
    </div>
  );
}
