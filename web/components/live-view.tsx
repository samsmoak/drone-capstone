"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { FlightRow, TelemetryRow, ZoneRow } from "@/lib/queries";
import { latestRow, useLiveStore } from "@/lib/store";
import { useFlightChanges, useLiveTelemetry } from "@/lib/use-live-telemetry";
import { ErrorState, LoadingState, Stat } from "@/components/ui/states";
import { TimeSeries } from "@/components/ui/time-series";
import { FlightPath } from "@/components/ui/flight-path";
import { batteryStatus } from "@/lib/flight-format";

/**
 * How long without a reading before the page says the feed has gone quiet.
 *
 * The agent logs at 10 Hz. Two seconds is twenty missed rows — not jitter. A
 * number that stops changing looks exactly like a drone holding steady, so
 * staleness is announced rather than left for the operator to notice.
 */
const STALE_AFTER_S = 2;

function formatAge(seconds: number): string {
  if (seconds < 120) return `${Math.floor(seconds)} s`;
  if (seconds < 7200) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h`;
}

function FeedBanner({ lastAt }: { lastAt: string | null }) {
  const status = useLiveStore((s) => s.status);
  const error = useLiveStore((s) => s.error);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);

  if (status === "error") {
    return (
      <ErrorState
        title="The live feed is down"
        detail={`${error ?? "Unknown error"} The readings below stopped updating when it failed.`}
        retry={
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
          >
            Reconnect
          </button>
        }
      />
    );
  }

  const age = lastAt ? (now - Date.parse(lastAt)) / 1000 : null;
  const stale = status === "live" && age !== null && age > STALE_AFTER_S;

  const [icon, color, text] =
    status === "connecting"
      ? ["○", "var(--muted)", "Connecting to the live feed…"]
      : stale
        ? ["▲", "var(--status-warning)", `No new readings for ${formatAge(age!)}`]
        : ["●", "var(--status-good)", "Live"];

  return (
    <p
      role="status"
      aria-live="polite"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm"
    >
      {/* Icon + words; the colour is a second signal, never the only one. */}
      <span aria-hidden="true" style={{ color }}>
        {icon}
      </span>
      <span className="font-medium">{text}</span>
      {stale && (
        <span className="text-[var(--muted)]">
          The drone may have landed, or the agent may have lost its connection to Supabase.
        </span>
      )}
    </p>
  );
}

export function LiveView({
  flight,
  initial,
  zones,
}: {
  flight: FlightRow | null;
  initial: TelemetryRow[];
  zones: ZoneRow[];
}) {
  const router = useRouter();
  const refresh = useCallback(() => router.refresh(), [router]);

  useLiveTelemetry(flight?.id ?? null, initial);
  // A flight starting or finishing re-reads the page, so it follows the drone
  // without a manual reload.
  useFlightChanges(refresh);

  const rows = useLiveStore((s) => s.rows);
  const status = useLiveStore((s) => s.status);

  if (!flight) {
    return (
      <div className="space-y-4">
        <p
          role="status"
          className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm"
        >
          <span className="font-medium">No flight in progress.</span>{" "}
          <span className="text-[var(--muted)]">
            This page updates by itself when the drone takes off — there is no need to reload.
          </span>
        </p>
      </div>
    );
  }

  const last = latestRow(rows);
  const unit = flight.temp_unit;
  const battery = last?.battery_v ?? null;
  // `z_m` is already height above the floor — see telemetry/reader.py.
  const height = last?.z_m ?? null;
  const first = rows[0]?.recorded_at;

  const series = rows.map((r) => ({
    t: first ? Math.round((Date.parse(r.recorded_at) - Date.parse(first)) / 100) / 10 : 0,
    corrected_temp: r.corrected_temp,
    height_m: r.z_m,
    battery_v: r.battery_v,
  }));

  return (
    <div className="space-y-8">
      <FeedBanner lastAt={last?.recorded_at ?? null} />

      <section aria-label="Current readings" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Height above ground"
          value={height !== null ? height.toFixed(2) : null}
          unit="m"
          hint={flight.ground_z_m != null
            ? `Floor at Lighthouse z ${flight.ground_z_m.toFixed(2)} m`
            : undefined}
        />
        <Stat
          label="Battery"
          value={battery !== null ? battery.toFixed(2) : null}
          unit="V"
          status={batteryStatus(battery)}
          hint={battery !== null && battery < 3.75 ? "Below the arming threshold" : undefined}
        />
        <Stat
          label={`Temperature (°${unit})`}
          value={last?.corrected_temp != null ? last.corrected_temp.toFixed(1) : null}
          unit={`°${unit}`}
          hint="Corrected for onboard heat"
        />
        <Stat
          label="Mode"
          value={last?.mode ?? null}
          hint={last?.event ? `Last event: ${last.event}` : undefined}
        />
      </section>

      {status === "connecting" && rows.length === 0 ? (
        <LoadingState label="Waiting for the first readings" rows={4} />
      ) : (
        <div className="grid gap-10 lg:grid-cols-2">
          <section aria-labelledby="live-height" className="space-y-3">
            <h2 id="live-height" className="text-lg font-semibold text-[var(--heading)]">
              Height above ground (m)
            </h2>
            <TimeSeries
              rows={series}
              xKey="t"
              xLabel="Time (s)"
              xFormat="seconds"
              yLabel="m"
              digits={3}
              series={[{ key: "height_m", label: "Height", slot: 1, unit: "m" }]}
            />
          </section>
          <section aria-labelledby="live-path" className="space-y-3">
            <h2 id="live-path" className="text-lg font-semibold text-[var(--heading)]">
              Position
            </h2>
            <FlightPath rows={rows} zones={zones} />
          </section>
          <section aria-labelledby="live-temp" className="space-y-3">
            <h2 id="live-temp" className="text-lg font-semibold text-[var(--heading)]">
              Temperature (°{unit})
            </h2>
            <TimeSeries
              rows={series}
              xKey="t"
              xLabel="Time (s)"
              xFormat="seconds"
              yLabel={`°${unit}`}
              series={[{ key: "corrected_temp", label: "Corrected", slot: 1, unit: `°${unit}` }]}
            />
          </section>
          <section aria-labelledby="live-battery" className="space-y-3">
            <h2 id="live-battery" className="text-lg font-semibold text-[var(--heading)]">
              Battery (V)
            </h2>
            <TimeSeries
              rows={series}
              xKey="t"
              xLabel="Time (s)"
              xFormat="seconds"
              yLabel="V"
              series={[{ key: "battery_v", label: "Battery", slot: 1, unit: "V" }]}
            />
          </section>
        </div>
      )}
    </div>
  );
}
