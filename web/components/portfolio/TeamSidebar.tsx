import Link from "next/link";
import type { ProjectCard, TeamMemberRow } from "@/lib/queries";
import { projectPath, TEAM } from "@/lib/routes";
import { TeamCard } from "./TeamCard";

/**
 * The right-hand column of a project page.
 *
 * Adapted from ../doctor-portfolio's ProjectsSidebar: the owner's photo became
 * the team that worked on this project, and the all-projects list stays below.
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
    <div className="grid gap-6 lg:sticky lg:top-24">
      <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="eyebrow mb-5">The team</h2>
        {team.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">
            No one is listed on this project yet.{" "}
            <Link href={TEAM} className="underline underline-offset-4">Meet the team</Link>.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-6 lg:grid-cols-1">
            {team.map((member) => <TeamCard key={member.id} member={member} compact />)}
          </div>
        )}
      </section>

      {projects.length > 1 && (
        <nav aria-label="All projects" className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
          <h2 className="eyebrow mb-3">All projects</h2>
          <ul className="space-y-1">
            {projects.map((p) => {
              const active = p.slug === activeSlug;
              return (
                <li key={p.id}>
                  <Link
                    href={projectPath(p.slug)}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded-lg px-3 py-2.5 text-sm leading-snug transition-colors ${
                      active
                        ? "bg-[var(--surface-2)] font-semibold text-[var(--heading)]"
                        : "hover:bg-[var(--surface-2)]"
                    }`}
                  >
                    {p.title}
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
