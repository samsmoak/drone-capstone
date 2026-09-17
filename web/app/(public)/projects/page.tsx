import type { Metadata } from "next";
import { ProjectCard } from "@/components/portfolio/ProjectCard";
import { getPublishedProjects } from "@/lib/queries";

export const metadata: Metadata = {
  title: "Projects",
  description: "The work behind CropWatcher: flight, sensing, safety and the software around them.",
};

export default async function ProjectsPage() {
  const projects = await getPublishedProjects();

  return (
    <main className="mx-auto max-w-6xl px-6 py-16 md:py-20">
      <p className="eyebrow text-[var(--heading)]">Portfolio</p>
      <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">Projects</h1>
      <p className="mt-4 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">
        The pieces that make CropWatcher fly, sense and stay safe — each written up by the people who
        built it.
      </p>

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
