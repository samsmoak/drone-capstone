"use client";

import { useId, useMemo, useState, useTransition } from "react";
import type { ZoneRow } from "@/lib/queries";
import { queuePlannedMission } from "@/lib/mutations";
import { metresToFeet } from "@/lib/flight-format";
import {
  ALTITUDE_MAX_M,
  ALTITUDE_MIN_M,
  HOLD_MAX_S,
  buildPlan,
  estimatedDurationS,
  validatePlan,
} from "@/lib/mission-plan";

/**
 * Click zones → waypoints → validate → queue.
 *
 * The order zones are clicked is the order they are flown, and the map numbers
 * them so the route can be checked by eye before anything is queued. Every zone
 * is also a real button in a list, so the whole planner works from a keyboard.
 */

const SIZE_W = 560;
const PAD = 8;

export function MissionPlanner({ zones, canQueue }: { zones: ZoneRow[]; canQueue: boolean }) {
  const [zoneIds, setZoneIds] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [altitude, setAltitude] = useState("0.5");
  const [hold, setHold] = useState("2");
  const [returnToStart, setReturnToStart] = useState(true);
  const [result, setResult] = useState<{ ok: boolean; message: string; problems?: string[] } | null>(null);
  const [pending, startTransition] = useTransition();
  const ids = { name: useId(), altitude: useId(), hold: useId(), problems: useId() };

  const plan = useMemo(
    () =>
      buildPlan(
        { name, altitudeM: Number(altitude), holdS: Number(hold), returnToStart, zoneIds },
        zones,
      ),
    [name, altitude, hold, returnToStart, zoneIds, zones],
  );
  const problems = validatePlan(plan);

  const toggleZone = (id: string) => {
    setResult(null);
    setZoneIds((current) =>
      current.includes(id) ? current.filter((z) => z !== id) : [...current, id],
    );
  };

  const submit = () => {
    if (problems.length > 0 || pending) return;
    startTransition(async () => {
      const response = await queuePlannedMission({
        name,
        altitudeM: Number(altitude),
        holdS: Number(hold),
        returnToStart,
        zoneIds,
      });
      if (response.ok) {
        setResult({ ok: true, message: `“${plan.name}” is queued. The agent picks it up on its next poll.` });
        setZoneIds([]);
        setName("");
      } else {
        setResult({ ok: false, message: response.error, problems: response.problems });
      }
    });
  };

  // Map geometry, equal scale on both axes.
  const x0 = Math.min(...zones.map((z) => z.x_min));
  const x1 = Math.max(...zones.map((z) => z.x_max));
  const y0 = Math.min(...zones.map((z) => z.y_min));
  const y1 = Math.max(...zones.map((z) => z.y_max));
  const scale = (SIZE_W - PAD * 2) / (x1 - x0);
  const height = (y1 - y0) * scale + PAD * 2;
  const sx = (x: number) => PAD + (x - x0) * scale;
  const sy = (y: number) => PAD + (y1 - y) * scale;
  const inBounds = (x: number, y: number) => x >= x0 && x <= x1 && y >= y0 && y <= y1;

  const route = [
    ...(inBounds(0, 0) ? [{ x: 0, y: 0 }] : []),
    ...plan.waypoints,
    ...(returnToStart && inBounds(0, 0) ? [{ x: 0, y: 0 }] : []),
  ];
  const duration = estimatedDurationS(plan);
  const altitudeM = Number(altitude);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="space-y-4">
        {/* A map shrunk to a phone's width renders its labels at ~6 px. Below
            its natural width it scrolls inside this box instead; the page itself
            never scrolls sideways, and the zone buttons below need no map. */}
        <div
          tabIndex={0}
          role="region"
          aria-label="Route map"
          className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
        >
          <svg
            viewBox={`0 0 ${SIZE_W} ${height}`}
            className="h-auto w-full min-w-[480px]"
            role="img"
            aria-label={`Planned route over ${zones.length} zones. ${plan.waypoints.length} chosen, in order: ${plan.waypoints.map((w) => w.label).join(", ") || "none"}.`}
          >
            {zones.map((z) => {
              const order = zoneIds.indexOf(z.id);
              const chosen = order >= 0;
              return (
                <g key={z.id} onClick={() => toggleZone(z.id)} className="cursor-pointer">
                  <rect
                    x={sx(z.x_min) + 1}
                    y={sy(z.y_max) + 1}
                    width={sx(z.x_max) - sx(z.x_min) - 2}
                    height={sy(z.y_min) - sy(z.y_max) - 2}
                    rx={4}
                    fill={chosen ? "var(--surface)" : "var(--surface-2)"}
                    stroke={chosen ? "var(--primary)" : "var(--border)"}
                    strokeWidth={chosen ? 2.5 : 1.5}
                  />
                  <text x={sx(z.x_min) + 8} y={sy(z.y_max) + 18} fontSize={12} fill="var(--muted)">
                    {z.label}
                  </text>
                </g>
              );
            })}

            {/* The route, in flight order, including the legs out of and back to takeoff. */}
            {route.length > 1 && (
              <polyline
                points={route.map((p) => `${sx(p.x)},${sy(p.y)}`).join(" ")}
                fill="none"
                stroke="var(--series-1)"
                strokeWidth={2}
                strokeDasharray="6 4"
                pointerEvents="none"
              />
            )}
            {inBounds(0, 0) && (
              <g pointerEvents="none">
                <circle cx={sx(0)} cy={sy(0)} r={6} fill="var(--surface)" stroke="var(--foreground)" strokeWidth={2} />
                <text x={sx(0) + 9} y={sy(0) - 8} fontSize={11} fill="var(--foreground)">
                  Takeoff
                </text>
              </g>
            )}
            {plan.waypoints.map((wp, i) => (
              <g key={`${wp.label}-${i}`} pointerEvents="none">
                <circle cx={sx(wp.x)} cy={sy(wp.y)} r={12} fill="var(--primary)" />
                <text
                  x={sx(wp.x)}
                  y={sy(wp.y) + 4}
                  fontSize={12}
                  fontWeight={600}
                  textAnchor="middle"
                  fill="var(--on-primary)"
                >
                  {i + 1}
                </text>
              </g>
            ))}
          </svg>
        </div>

        {/* The same choice as the map, as real buttons: keyboard and screen reader path. */}
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Zones, in the order they will be flown</legend>
          <ul className="flex flex-wrap gap-2">
            {zones.map((z) => {
              const order = zoneIds.indexOf(z.id);
              return (
                <li key={z.id}>
                  <button
                    type="button"
                    onClick={() => toggleZone(z.id)}
                    aria-pressed={order >= 0}
                    className={`inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border px-3 text-sm ${
                      order >= 0
                        ? "border-[var(--primary)] bg-[var(--surface)] font-medium"
                        : "border-[var(--border)]"
                    }`}
                  >
                    {order >= 0 && <span className="tabular">{order + 1}.</span>}
                    {z.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </fieldset>
      </div>

      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        aria-describedby={problems.length > 0 ? ids.problems : undefined}
      >
        <div className="space-y-1.5">
          <label htmlFor={ids.name} className="block text-sm font-medium">
            Mission name
          </label>
          <input
            id={ids.name}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Morning scan, bench A"
            className="min-h-11 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor={ids.altitude} className="block text-sm font-medium">
            Altitude above the ground (m)
          </label>
          <input
            id={ids.altitude}
            type="number"
            inputMode="decimal"
            step="0.05"
            min={ALTITUDE_MIN_M}
            max={ALTITUDE_MAX_M}
            value={altitude}
            onChange={(e) => setAltitude(e.target.value)}
            className="tabular min-h-11 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3"
          />
          {/* Metres are the unit; feet appear only as a label. */}
          <p className="text-xs text-[var(--muted)]">
            {Number.isFinite(altitudeM) ? `≈ ${metresToFeet(altitudeM).toFixed(1)} ft. ` : ""}
            Measured from the floor at takeoff, not from Lighthouse zero.
          </p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor={ids.hold} className="block text-sm font-medium">
            Hold at each zone (s)
          </label>
          <input
            id={ids.hold}
            type="number"
            inputMode="decimal"
            step="1"
            min={0}
            max={HOLD_MAX_S}
            value={hold}
            onChange={(e) => setHold(e.target.value)}
            className="tabular min-h-11 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3"
          />
        </div>

        <label className="flex min-h-11 items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={returnToStart}
            onChange={(e) => setReturnToStart(e.target.checked)}
            className="h-5 w-5"
          />
          Return to the takeoff point before landing
        </label>

        <dl className="grid grid-cols-2 gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm">
          <div>
            <dt className="text-xs text-[var(--muted)]">Zones</dt>
            <dd className="tabular text-lg font-semibold">{plan.waypoints.length}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--muted)]">Estimated flight</dt>
            <dd className="tabular text-lg font-semibold">
              {plan.waypoints.length > 0 ? `${Math.round(duration)} s` : "—"}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-xs text-[var(--muted)]">Per leg</dt>
            <dd className="tabular">{plan.leg_duration_s} s, sized from the longest leg</dd>
          </div>
        </dl>

        {problems.length > 0 && (
          <div id={ids.problems} className="space-y-1 text-sm">
            <p className="font-medium">Before this can be queued:</p>
            <ul className="list-disc space-y-1 pl-5 text-[var(--muted)]">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        )}

        {result && (
          <div
            role={result.ok ? "status" : "alert"}
            className="rounded-lg border bg-[var(--surface)] p-3 text-sm"
            style={{ borderColor: result.ok ? "var(--status-good)" : "var(--status-critical)" }}
          >
            <p className="flex items-start gap-2 font-medium">
              <span aria-hidden="true" style={{ color: result.ok ? "var(--status-good)" : "var(--status-critical)" }}>
                {result.ok ? "●" : "⚠"}
              </span>
              {result.message}
            </p>
            {result.problems && (
              <ul className="mt-2 list-disc pl-5">
                {result.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!canQueue && (
          <p className="text-sm text-[var(--muted)]">
            Your account is a viewer. You can plan a route, but only an operator can queue it.
          </p>
        )}

        <button
          type="submit"
          disabled={problems.length > 0 || pending || !canQueue}
          className="inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)] disabled:opacity-50"
        >
          {pending ? "Queuing…" : "Queue mission"}
        </button>
        <p className="text-xs text-[var(--muted)]">
          The agent checks the plan again against its geofence and obstacle map before it arms.
          Look at the room before a mission flies — the map does not know about people.
        </p>
      </form>
    </div>
  );
}
