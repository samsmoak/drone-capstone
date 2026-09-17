import Image from "next/image";
import Link from "next/link";
import { categoryColor } from "@/lib/categories";
import type { ProjectCard, TeamMemberRow } from "@/lib/queries";
import { memberPath, projectPath, TEAM } from "@/lib/routes";

/**
 * The right-hand column of a person's page: everyone else on the team, then the
 * projects this person worked on.
 *
 * Adapted from TeamSidebar (itself from ../doctor-portfolio's ProjectsSidebar):
 * same card, same per-row accent, same active state — the rows are people
 * rather than projects, so each carries a photo and links to that person.
 */
export function MemberSidebar({
  team,
  projects,
  activeId,
}: {
  team: TeamMemberRow[];
  projects: ProjectCard[];
  activeId: string;
}) {
  return (
    <div className="grid gap-5">
      <nav aria-label="The team" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <h2 className="eyebrow mb-3">The team</h2>
        <ul className="grid gap-1.5">
          {team.map((person) => {
            const active = person.id === activeId;
            const accent = categoryColor(person.full_name);
            const initial = person.full_name.trim().charAt(0).toUpperCase();
            const row = (
              <>
                <span
                  aria-hidden="true"
                  className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-[var(--accent)]"
                />
                <span
                  className="relative h-9 w-9 shrink-0 overflow-hidden rounded-full"
                  style={{ background: `color-mix(in srgb, var(--accent) 22%, var(--surface))` }}
                >
                  {person.avatar_url ? (
                    <Image src={person.avatar_url} alt="" fill sizes="36px" className="object-cover" />
                  ) : (
                    <span className="font-display flex h-full w-full items-center justify-center text-sm font-semibold">
                      {initial}
                    </span>
                  )}
                </span>
                <span className="min-w-0">
                  <span className={`block truncate text-sm leading-snug ${active ? "font-semibold" : "font-medium"}`}>
                    {person.full_name}
                  </span>
                  {person.role && (
                    <span className="block truncate text-xs text-[var(--muted)]">{person.role}</span>
                  )}
                </span>
              </>
            );
            const shell =
              "group relative flex items-center gap-3 overflow-hidden rounded-xl border py-2 pl-4 pr-3 transition-all duration-200";
            return (
              <li key={person.id} style={{ "--accent": accent } as React.CSSProperties}>
                {active ? (
                  <span
                    aria-current="page"
                    className={`${shell} border-[color-mix(in_srgb,var(--accent)_45%,transparent)] bg-[color-mix(in_srgb,var(--accent)_12%,var(--surface))]`}
                  >
                    {row}
                  </span>
                ) : (
                  <Link
                    href={memberPath(person.slug ?? "")}
                    className={`${shell} border-transparent hover:translate-x-0.5 hover:bg-[color-mix(in_srgb,var(--accent)_8%,var(--surface))]`}
                  >
                    {row}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
        <Link
          href={TEAM}
          className="mt-3 inline-block text-xs font-medium text-[var(--heading)] underline-offset-4 hover:underline"
        >
          Everyone on one page
        </Link>
      </nav>

      {projects.length > 0 && (
        <nav aria-label="Their projects" className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <h2 className="eyebrow mb-3">Worked on</h2>
          <ul className="grid gap-1.5">
            {projects.map((p) => {
              const accent = categoryColor(p.category);
              return (
                <li key={p.id}>
                  <Link
                    href={projectPath(p.slug)}
                    style={{ "--accent": accent } as React.CSSProperties}
                    className="group relative block overflow-hidden rounded-xl border border-transparent py-2.5 pl-4 pr-3 transition-all duration-200 hover:translate-x-0.5 hover:bg-[color-mix(in_srgb,var(--accent)_8%,var(--surface))]"
                  >
                    <span aria-hidden="true" className="absolute inset-y-2 left-1.5 w-1 rounded-full bg-[var(--accent)]" />
                    <span className="block text-sm font-medium leading-snug">{p.title}</span>
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
