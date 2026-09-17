import Link from "next/link";
import { categoryColor } from "@/lib/categories";
import type { ProjectCard, TeamMemberRow } from "@/lib/queries";
import { projectPath, TEAM } from "@/lib/routes";
import { TeamStack } from "./TeamStack";

/**
 * The right-hand column of a project page: the team as a card stack, then every
 * project, each in its category's colour.
 *
 * Adapted from ../doctor-portfolio's ProjectsSidebar: the owner's photo became
 * the project's team, and the list keeps the per-category colour coding.
 */
export function TeamSidebar({
  team,
  projects,
  activeSlug,
}: {
  team: TeamMemberRow[];
  projects: ProjectCard[];
  activeSlug: string;
}) {
  return (
    <div className="grid gap-5">
      {team.length === 0 ? (
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <h2 className="eyebrow">The team</h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            No one is listed on this project yet. <Link href={TEAM} className="underline underline-offset-4">Meet the team</Link>.
          </p>
        </section>
      ) : (
        <TeamStack team={team} />
      )}

      {projects.length > 1 && (
        <nav aria-label="All projects" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <h2 className="eyebrow mb-3">All projects</h2>
          <ul className="grid gap-1.5">
            {projects.map((p) => {
              const active = p.slug === activeSlug;
              const accent = categoryColor(p.category);
              return (
                <li key={p.id}>
                  <Link
                    href={projectPath(p.slug)}
                    aria-current={active ? "page" : undefined}
                    style={{ "--accent": accent } as React.CSSProperties}
                    className={`group relative block overflow-hidden rounded-xl border py-2.5 pl-4 pr-3 transition-all duration-200 ${
                      active
                        ? "border-[color-mix(in_srgb,var(--accent)_45%,transparent)] bg-[color-mix(in_srgb,var(--accent)_12%,var(--surface))]"
                        : "border-transparent hover:translate-x-0.5 hover:bg-[color-mix(in_srgb,var(--accent)_8%,var(--surface))]"
                    }`}
                  >
                    <span aria-hidden="true" className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-[var(--accent)]" />
                    <span className={`block text-sm leading-snug ${active ? "font-semibold" : "font-medium"}`}>{p.title}</span>
                    {p.category && (
                      <span className="mt-1 inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted)]">
                        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                        {p.category}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </div>
  );
}
