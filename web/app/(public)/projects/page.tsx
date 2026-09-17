import type { Metadata } from "next";
import { ProjectCard } from "@/components/portfolio/ProjectCard";
import { PageIntro } from "@/components/site/PageIntro";
import { getPageContent, getPublishedProjects } from "@/lib/queries";

export const metadata: Metadata = {
  title: "Projects",
  description: "The work behind CropWatcher: flight, sensing, safety and the software around them.",
};

export default async function ProjectsPage() {
  const [projects, intro] = await Promise.all([getPublishedProjects(), getPageContent("projects")]);

  return (
    <main className="mx-auto max-w-6xl px-6 py-16 md:py-20">
      <PageIntro content={intro} />

      {projects.length === 0 ? (
        <div className="mt-16 rounded-xl border border-dashed border-[var(--border)] p-16 text-center">
          <p className="text-[var(--muted)]">No projects published yet.</p>
        </div>
      ) : (
        <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((project, i) => (
            <ProjectCard key={project.id} project={project} priority={i < 3} />
          ))}
        </div>
      )}
    </main>
  );
}
