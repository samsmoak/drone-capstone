import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { TableOfContents } from "@/components/portfolio/TableOfContents";
import { TeamSidebar } from "@/components/portfolio/TeamSidebar";
import { renderProjectContent } from "@/lib/blocknote/render";
import { getPublishedProjectBySlug, getPublishedProjects } from "@/lib/queries";
import { PROJECTS } from "@/lib/routes";

export async function generateMetadata({ params }: PageProps<"/projects/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const project = await getPublishedProjectBySlug(slug).catch(() => null);
  if (!project) return { title: "Project not found" };
  return { title: project.title, description: project.summary || project.subtitle || undefined };
}

/**
 * A project: contents on the left, the write-up in the middle, the team who
 * built it on the right. Layout copied from ../doctor-portfolio's project page.
 */
export default async function ProjectPage({ params }: PageProps<"/projects/[slug]">) {
  const { slug } = await params;
  const [project, allProjects] = await Promise.all([
    getPublishedProjectBySlug(slug),
    getPublishedProjects(),
  ]);
  if (!project) notFound();

  const { html, sections } = await renderProjectContent(project.content);

  return (
    <main className="mx-auto max-w-[96rem] px-6 py-10 md:py-14">
      <Link
        href={PROJECTS}
        className="mb-8 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        All projects
      </Link>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        <aside className="hidden lg:col-span-2 lg:block">
          <TableOfContents sections={sections} />
        </aside>

        <article className="min-w-0 lg:col-span-7">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-sm sm:p-9 lg:p-10">
            {project.category && <p className="eyebrow text-[var(--heading)]">{project.category}</p>}
            <h1 className="font-display mt-3 text-3xl font-semibold leading-tight sm:text-4xl">
              {project.title}
            </h1>
            {project.subtitle && (
              <p className="mt-3 text-lg leading-relaxed text-[var(--muted)]">{project.subtitle}</p>
            )}
            {(project.date_label || project.location) && (
              <p className="eyebrow mt-4">
                {[project.date_label, project.location].filter(Boolean).join(" · ")}
              </p>
            )}

            {project.cover_image_url && (
              <div className="relative mt-7 aspect-[16/9] overflow-hidden rounded-lg border border-[var(--border)]">
                <Image
                  src={project.cover_image_url}
                  alt=""
                  fill
                  priority
                  sizes="(max-width: 1024px) 100vw, 55vw"
                  className="object-cover"
                />
              </div>
            )}

            {html ? (
              <div className="portfolio-prose mt-8" dangerouslySetInnerHTML={{ __html: html }} />
            ) : (
              <p className="mt-8 italic text-[var(--muted)]">This project does not have a write-up yet.</p>
            )}
          </div>
        </article>

        {/* Sticky like the contents on the left. The team stays a stack until
            opened, so the column is short enough to stay in view. */}
        <aside className="lg:col-span-3 lg:sticky lg:top-24 lg:self-start">
          <TeamSidebar team={project.team} projects={allProjects} activeSlug={project.slug} />
        </aside>
      </div>
    </main>
  );
}
