/**
 * One live reading over the last minute.
 *
 * Copy-adapted from `web/components/ui/time-series.tsx`, keeping the rules that
 * matter and dropping what a live window does not need:
 *
 * - **The y-axis fits the data, with round ticks.** A battery moving 4.1 → 3.7 V
 *   drawn from zero is a flat line, and the chart says nothing.
 * - **Recessive furniture, text in text tokens.** `--axis` measures 2.86:1, so
 *   it draws lines only; labels use `--muted`.
 * - **No legend:** one series, and the panel title names it (the web's table
 *   view is the relief for the low-contrast series colours; a single
 *   `--series-1` line does not need it).
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

export type Sample = { t: number; value: number | null };

const AXIS_TICK = { fill: "var(--muted)", fontSize: 11 };

/** A scale that fits the data and ticks on round numbers. */
function niceScale(samples: Sample[]): { domain: [number, number]; ticks: number[] } {
  const values = samples.map((s) => s.value).filter((v): v is number => v !== null);
  if (values.length === 0) return { domain: [0, 1], ticks: [0, 1] };

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) * 0.1 || 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(span / 4)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= span / 4) ?? span / 4;
  let lo = Math.floor(min / step) * step;
  let hi = Math.ceil(max / step) * step;
  if (lo === hi) {
    lo -= step;
    hi += step;
  }
  const decimals = Math.max(0, -Math.floor(Math.log10(step)) + 1);
  const round = (n: number) => Number(n.toFixed(decimals));
  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(round(t));
  return { domain: [round(lo), round(hi)], ticks };
}

export function LiveChart({
  samples, unit, height = 150,
}: {
  samples: Sample[];
  unit: string;
  height?: number;
}) {
  if (samples.length === 0) {
    return (
      <p className="flex h-[150px] items-center text-sm text-[var(--muted)]">
        Waiting for readings…
      </p>
    );
  }
  const scale = niceScale(samples);

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <LineChart data={samples} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={{ stroke: "var(--grid)" }}
            tickFormatter={(v) => `${Math.round(Number(v))}s`}
            minTickGap={28}
          />
          <YAxis
            domain={scale.domain}
            ticks={scale.ticks}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={52}
            label={{ value: unit, angle: -90, position: "insideLeft",
                     fill: "var(--muted)", fontSize: 11 }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
