import { PROSE_COLUMN, SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import { ProjectCard } from "@/components/portfolio/ProjectCard";
import { PageIntro } from "@/components/site/PageIntro";
import { PartCards } from "@/components/site/PartCards";
import { getPageContent, getPublishedProjects } from "@/lib/queries";
import { items, text } from "@/lib/site-content";

export const metadata: Metadata = {
  title: "Projects",
  description: "The six parts of DroneDeck — apps, autonomous flight, data collection, anomaly detection, documentation and testing — one write-up each.",
};

/**
 * The six parts first — the same cards as the home page, from the same field
 * (PartCards) — then every other published write-up: the overview, the team's
 * design document, anything added in /admin. A part is never listed twice:
 * a project whose page a part card links to is left out of the second list.
 */
export default async function ProjectsPage() {
  const [projects, intro, home] = await Promise.all([
    getPublishedProjects(),
    getPageContent("projects"),
    getPageContent("home"),
  ]);
  const parts = items(home, "capabilities");
  const partHrefs = new Set(parts.map((p) => text(p, "href")).filter(Boolean));
  const others = projects.filter((p) => !partHrefs.has(`/projects/${p.slug}`));

  return (
    <main className={`${SITE_CONTAINER} py-16 md:py-20`}>
      <PageIntro content={intro} />

      {parts.length > 0 && (
        <section aria-labelledby="parts-heading" className="mt-12">
          <div className={PROSE_COLUMN}>
            <h2 id="parts-heading" className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
              {text(home, "capabilitiesTitle")}
            </h2>
            {text(home, "capabilitiesIntro") && (
              <p className="mt-3 leading-relaxed text-[var(--muted)]">{text(home, "capabilitiesIntro")}</p>
            )}
          </div>
          <PartCards parts={parts} className="mt-8" />
        </section>
      )}

      {others.length > 0 && (
        <section aria-labelledby="more-heading" className="mt-16">
          <h2 id="more-heading" className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
            The whole system, and the design behind it
          </h2>
          <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {others.map((project, i) => (
              <ProjectCard key={project.id} project={project} priority={i < 3} />
            ))}
          </div>
        </section>
      )}

      {parts.length === 0 && others.length === 0 && (
        <div className="mt-16 rounded-xl border border-dashed border-[var(--border)] p-16 text-center">
          <p className="text-[var(--muted)]">No projects published yet.</p>
        </div>
      )}
    </main>
  );
}
