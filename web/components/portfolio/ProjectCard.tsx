import Image from "next/image";
import Link from "next/link";
import { categoryColor } from "@/lib/categories";
import type { ProjectCard as ProjectCardData } from "@/lib/queries";
import { projectPath } from "@/lib/routes";

/**
 * A project in the grid. Copied from ../doctor-portfolio's ProjectCard, drawn
 * with this site's tokens; the cover carousel became a single cover.
 */
export function ProjectCard({ project, priority = false }: { project: ProjectCardData; priority?: boolean }) {
  return (
    <Link
      href={projectPath(project.slug)}
      className="group flex h-full flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="relative aspect-[16/9] w-full overflow-hidden bg-[var(--surface-2)]">
        {project.cover_image_url ? (
          <Image
            src={project.cover_image_url}
            alt=""
            fill
            priority={priority}
            sizes="(max-width: 768px) 100vw, 33vw"
            className="object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <span className="font-display text-4xl text-[var(--muted)] opacity-50">
              {project.title.charAt(0)}
            </span>
          </div>
        )}
        {project.category && (
          <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-md bg-[var(--surface)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider shadow-sm">
            <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ background: categoryColor(project.category) }} />
            {project.category}
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-6">
        {(project.date_label || project.location) && (
          <p className="eyebrow mb-2">
            {[project.date_label, project.location].filter(Boolean).join(" · ")}
          </p>
        )}
        <h2 className="font-display text-xl font-semibold leading-snug transition-colors group-hover:text-[var(--heading)]">
          {project.title}
        </h2>
        {project.summary && (
          <p className="mt-2.5 line-clamp-3 text-sm leading-relaxed text-[var(--muted)]">{project.summary}</p>
        )}
        <span className="mt-auto inline-flex items-center gap-1.5 self-start pt-5 text-sm font-semibold text-[var(--heading)]">
          View project
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"
               className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </span>
      </div>
    </Link>
  );
}
