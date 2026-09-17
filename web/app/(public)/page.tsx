import Link from "next/link";
import { getPageContent } from "@/lib/queries";
import { OPERATOR_HOME, PROJECTS, TEAM } from "@/lib/routes";
import { items, text } from "@/lib/site-content";

export const metadata = {
  title: "CropWatcher — autonomous crop-health monitoring",
  description:
    "An indoor greenhouse scouting system built on a Crazyflie 2.1: autonomous flight, " +
    "position-tagged environmental data, and zone-level crop-health estimates.",
};

/** The landing page. Every word here is edited at /admin/pages/home. */
export default async function LandingPage() {
  const home = await getPageContent("home");

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <section>
        <p className="eyebrow text-[var(--heading)]">{text(home, "eyebrow")}</p>
        <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight sm:text-6xl">{text(home, "title")}</h1>
        <p className="mt-5 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">{text(home, "intro")}</p>

        <div className="mt-8 flex flex-wrap gap-3">
          <Link href={PROJECTS}
                className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)]">
            {text(home, "primaryCta")}
          </Link>
          <Link href={OPERATOR_HOME}
                className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 font-medium">
            {text(home, "secondaryCta")}
          </Link>
        </div>
      </section>

      <section className="mt-16 grid gap-4 sm:grid-cols-2">
        {items(home, "capabilities").map((item, i) => (
          <article key={`${text(item, "title")}-${i}`} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <h2 className="font-display text-lg font-semibold">{text(item, "title")}</h2>
            <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{text(item, "body")}</p>
          </article>
        ))}
      </section>

      <section className="mt-16 border-t border-[var(--border)] pt-8">
        <p className="text-sm text-[var(--muted)]">
          {text(home, "teamLine")}{" "}
          <Link href={TEAM} className="underline underline-offset-4">{text(home, "teamLinkLabel")}</Link>.
        </p>
      </section>
    </main>
  );
}
