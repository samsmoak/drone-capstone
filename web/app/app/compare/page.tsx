import Link from "next/link";
import { getFlightTelemetry, getRecentFlights } from "@/lib/queries";
import { EmptyState, StatusBadge } from "@/components/ui/states";
import { PageHeader } from "@/components/ui/page-header";
import { TimeSeries } from "@/components/ui/time-series";
import { COMPARE, FLIGHTS } from "@/lib/routes";
import { flightDuration, flightStatusLabel, flightTone } from "@/lib/flight-format";
import {
  MAX_COMPARE,
  METRICS,
  compareHref,
  isMetric,
  mergeForChart,
  parseSelection,
  toggle,
  type Metric,
} from "@/lib/compare";
import { LocalTime } from "@/components/ui/local-time";

export const metadata = { title: "Compare flights" };

export default async function ComparePage(props: PageProps<"/app/compare">) {
  const params = await props.searchParams;
  const metric: Metric = isMetric(params.metric) ? params.metric : "corrected_temp";
  const flights = await getRecentFlights(50);

  if (flights.length === 0) {
    return (
      <div className="space-y-8">
        <PageHeader title="Compare flights" />
        <EmptyState
          title="No flights to compare"
          hint="Once two or more flights are recorded, they can be laid over each other here."
        />
      </div>
    );
  }

  // Only flights that still exist in the list; a stale id in a shared link is dropped.
  const selection = parseSelection(params.f).filter((s) => flights.some((f) => f.id === s.id));
  const selected = await Promise.all(
    selection.map(async (s) => ({
      ...s,
      flight: flights.find((f) => f.id === s.id)!,
      telemetry: await getFlightTelemetry(s.id),
    })),
  );

  const meta = METRICS[metric];
  // One axis means one unit. Temperatures stored in different units are
  // converted to the first selected flight's unit, and the page says so.
  const displayUnit = selected[0]?.flight.temp_unit ?? "C";
  const converted =
    meta.kind === "temp" ? selected.filter((s) => s.flight.temp_unit !== displayUnit) : [];
  const unit = meta.kind === "temp" ? `°${displayUnit}` : meta.unit;
  const digits = meta.kind === "temp" ? 2 : meta.digits;

  const rows = mergeForChart(selected, metric, displayUnit);
  // A flight with nothing to plot for this measure gets no legend entry: a
  // legend swatch with no line beside it reads as a line hidden under another.
  const plotted = selected.filter((s) => rows.some((r) => r[`f${s.slot}`] != null));
  const series = plotted.map((s) => ({
    key: `f${s.slot}`,
    // Named by start time, formatted in the viewer's timezone by the chart.
    label: s.flight.started_at,
    labelIsTime: true,
    slot: s.slot,
    unit,
  }));

  return (
    <div className="space-y-8">
      <PageHeader
        title="Compare flights"
        description={`Lay up to ${MAX_COMPARE} flights over each other, aligned by time since each one started.`}
      />

      <nav aria-label="Measure" className="flex flex-wrap gap-2">
        {(Object.keys(METRICS) as Metric[]).map((key) => (
          <Link
            key={key}
            href={compareHref(COMPARE, selection, key)}
            aria-current={key === metric ? "page" : undefined}
            className={`inline-flex min-h-11 items-center rounded-md border px-3 text-sm ${
              key === metric
                ? "border-[var(--primary)] bg-[var(--surface-2)] font-medium"
                : "border-[var(--border)] text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {METRICS[key].label}
          </Link>
        ))}
      </nav>

      <section aria-labelledby="chart-heading" className="space-y-3">
        <h2 id="chart-heading" className="text-lg font-semibold">
          {meta.label} ({unit})
        </h2>

        {selected.length === 0 ? (
          <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--muted)]">
            Choose flights from the list below to compare them.
          </p>
        ) : (
          <>
            {converted.length > 0 && (
              <p role="status" className="text-sm text-[var(--muted)]">
                {converted.length === 1 ? "One flight was" : `${converted.length} flights were`}{" "}
                recorded in °{converted[0].flight.temp_unit} and converted to °{displayUnit} for
                this chart.
              </p>
            )}
            {metric === "height_m" && selected.some((s) => s.flight.ground_z_m == null) && (
              <p role="status" className="text-sm text-[var(--muted)]">
                Flights without a ground reference are left out of height: raw Lighthouse z
                cannot be compared between flights.
              </p>
            )}
            <TimeSeries
              rows={rows}
              series={series}
              xKey="t"
              xLabel="Time since start (s)"
              xFormat="seconds"
              yLabel={unit}
              digits={digits}
            />
          </>
        )}
      </section>

      <section aria-labelledby="pick-heading" className="space-y-3">
        <h2 id="pick-heading" className="text-lg font-semibold">
          Flights{" "}
          <span className="text-sm font-normal text-[var(--muted)]">
            {selection.length} of {MAX_COMPARE} selected
          </span>
        </h2>
        <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-[var(--surface-2)]">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Compare</th>
                <th scope="col" className="px-4 py-3 font-medium">Started</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3 font-medium">Duration</th>
                <th scope="col" className="px-4 py-3 font-medium">Unit</th>
              </tr>
            </thead>
            <tbody>
              {flights.map((flight) => {
                const current = selection.find((s) => s.id === flight.id);
                const next = toggle(selection, flight.id);
                return (
                  <tr key={flight.id} className="border-t border-[var(--border)]">
                    <td className="px-4 py-2">
                      {next ? (
                        <Link
                          href={compareHref(COMPARE, next, metric)}
                          aria-pressed={Boolean(current)}
                          className={`inline-flex min-h-11 items-center gap-2 rounded-md border px-3 ${
                            current
                              ? "border-[var(--primary)] font-medium"
                              : "border-[var(--border)]"
                          }`}
                        >
                          {current && (
                            // The swatch ties the row to its line; the word carries the state.
                            <span
                              aria-hidden="true"
                              className="inline-block h-0.5 w-4"
                              style={{ background: `var(--series-${current.slot})` }}
                            />
                          )}
                          {current ? "Remove" : "Add"}
                          <span className="sr-only">
                            {" "}flight from <LocalTime iso={flight.started_at} />
                          </span>
                        </Link>
                      ) : (
                        <span className="text-xs text-[var(--muted)]">
                          {MAX_COMPARE} already selected
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <Link
                        href={`${FLIGHTS}/${flight.id}`}
                        className="inline-flex min-h-11 items-center underline underline-offset-4"
                      >
                        <LocalTime iso={flight.started_at} />
                      </Link>
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge
                        status={flightTone(flight.status)}
                        label={flightStatusLabel(flight.status)}
                      />
                    </td>
                    <td className="tabular px-4 py-2">
                      {flightDuration(flight.started_at, flight.ended_at)}
                    </td>
                    <td className="px-4 py-2">°{flight.temp_unit}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
