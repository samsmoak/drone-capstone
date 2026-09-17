import Link from "next/link";
import { OPERATOR_HOME, PROJECTS, TEAM } from "@/lib/routes";

export const metadata = {
  title: "CropWatcher — autonomous crop-health monitoring",
  description:
    "An indoor greenhouse scouting system built on a Crazyflie 2.1: autonomous flight, " +
    "position-tagged environmental data, and zone-level crop-health estimates.",
};

const CAPABILITIES = [
  {
    title: "Autonomous flight",
    body:
      "Lawnmower scans and custom waypoint routes, flown under closed-loop " +
      "position control with Lighthouse indoor positioning.",
  },
  {
    title: "Corrected sensing",
    body:
      "The barometer sits on a board that heats itself. A two-timescale thermal " +
      "model separates the electronics from the room, validated to 0.12 °F.",
  },
  {
    title: "Safety before arming",
    body:
      "Every plan is checked against a geofence and an obstacle map before a " +
      "motor spins — including the leg out of the takeoff point.",
  },
  {
    title: "Zone-level health",
    body:
      "Position-tagged readings become a greenhouse map, so a grower can see " +
      "which rows need attention rather than reading a spreadsheet.",
  },
];

export default function LandingPage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <section>
        <p className="text-sm font-medium uppercase tracking-widest text-[var(--muted)]">
          Capstone project
        </p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">
          CropWatcher
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-[var(--muted)]">
          An autonomous indoor scouting drone that flies a greenhouse, records
          position-tagged environmental data, and turns it into a crop-health map.
        </p>

        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href={PROJECTS}
            className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]"
          >
            See the projects
          </Link>
          <Link
            href={OPERATOR_HOME}
            className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 font-medium"
          >
            Operator dashboard
          </Link>
        </div>
      </section>

      <section className="mt-16 grid gap-4 sm:grid-cols-2">
        {CAPABILITIES.map((item) => (
          <article
            key={item.title}
            className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5"
          >
            <h2 className="font-medium">{item.title}</h2>
            <p className="mt-2 text-sm text-[var(--muted)]">{item.body}</p>
          </article>
        ))}
      </section>

      <section className="mt-16 border-t border-[var(--border)] pt-8">
        <p className="text-sm text-[var(--muted)]">
          Built on a Crazyflie 2.1 with Lighthouse positioning.{" "}
          <Link href={TEAM} className="underline underline-offset-4">
            Meet the team
          </Link>
          .
        </p>
      </section>
    </main>
  );
}
