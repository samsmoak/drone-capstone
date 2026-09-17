import { SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HobbyGrid } from "@/components/portfolio/HobbyGrid";
import { MemberLinks } from "@/components/portfolio/MemberLinks";
import { MemberSidebar } from "@/components/portfolio/MemberSidebar";
import { PhotoWall } from "@/components/portfolio/PhotoWall";
import { getProjectsForMember, getTeamMemberBySlug, getTeamMembers } from "@/lib/queries";
import { TEAM } from "@/lib/routes";
import { hobbies, links, paragraphs, photos } from "@/lib/team-profile";

export async function generateMetadata({ params }: PageProps<"/team/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const member = await getTeamMemberBySlug(slug).catch(() => null);
  if (!member) return { title: "Team member not found" };
  return {
    title: member.full_name,
    description: member.headline || member.bio || `${member.full_name} on the CropWatcher team.`,
  };
}

/** A section with a heading, shown only when it has something in it. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10 border-t border-[var(--border)] pt-8 first:mt-0 first:border-0 first:pt-0">
      <h2 className="font-display text-xl font-semibold tracking-tight">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/**
 * One person: who they are, what they are working on, what they do outside it,
 * their photos and their links — with the rest of the team on the right.
 *
 * The layout is the project page's (app/(public)/projects/[slug]/page.tsx),
 * itself copied from ../doctor-portfolio: main column, sticky sidebar. The
 * content sections follow that project's `story` page — intro with a portrait,
 * then sections, then a gallery.
 */
export default async function TeamMemberPage({ params }: PageProps<"/team/[slug]">) {
  const { slug } = await params;
  const member = await getTeamMemberBySlug(slug);
  if (!member) notFound();

  const [team, projects] = await Promise.all([
    getTeamMembers(),
    getProjectsForMember(member.id),
  ]);

  const about = paragraphs(member.about || member.bio);
  const theirHobbies = hobbies(member.hobbies);
  const theirPhotos = photos(member.photos);
  const theirLinks = links(member.links);
  const website = member.website_url;
  // The website column predates the links list (migration 0007). Show it as one
  // more link rather than making someone enter it twice.
  const allLinks = website && !theirLinks.some((l) => l.url === website)
    ? [{ label: "Website", url: website }, ...theirLinks]
    : theirLinks;

  const initial = member.full_name.trim().charAt(0).toUpperCase();
  const nothingYet =
    about.length === 0 && theirHobbies.length === 0 && theirPhotos.length === 0 && !member.current_work;

  return (
    <main className={`${SITE_CONTAINER} py-10 md:py-14`}>
      <Link
        href={TEAM}
        className="mb-8 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        The team
      </Link>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        <article className="min-w-0 lg:col-span-8 xl:col-span-9">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-sm sm:p-9 lg:p-10">
            {/* Intro: portrait beside the name, as on the portfolio's story page. */}
            <header className="grid gap-7 sm:grid-cols-[minmax(0,1fr)_14rem] sm:items-start sm:gap-9">
              <div className="min-w-0 sm:order-1">
                {member.role && <p className="eyebrow text-[var(--heading)]">{member.role}</p>}
                <h1 className="font-display mt-3 text-3xl font-semibold leading-tight sm:text-4xl">
                  {member.full_name}
                </h1>
                {member.headline && (
                  <p className="mt-3 text-lg leading-relaxed text-[var(--muted)]">{member.headline}</p>
                )}
                {member.location && <p className="eyebrow mt-4">{member.location}</p>}
                <div className="mt-6">
                  <MemberLinks links={allLinks} email={member.email} />
                </div>
              </div>

              <div className="relative aspect-[4/5] w-full max-w-56 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] sm:order-2">
                {member.avatar_url ? (
                  <Image
                    src={member.avatar_url}
                    alt={`Photo of ${member.full_name}`}
                    fill
                    priority
                    sizes="224px"
                    className="object-cover"
                  />
                ) : (
                  <span className="font-display flex h-full w-full items-center justify-center text-6xl text-[var(--heading)]">
                    {initial}
                  </span>
                )}
              </div>
            </header>

            <div className="mt-10">
              {member.current_work && (
                <Section title="Working on now">
                  <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 leading-relaxed">
                    {member.current_work}
                  </p>
                </Section>
              )}

              {about.length > 0 && (
                <Section title={`About ${member.full_name.split(" ")[0]}`}>
                  <div className="grid gap-4 leading-relaxed text-[var(--muted)]">
                    {about.map((para, i) => <p key={i}>{para}</p>)}
                  </div>
                </Section>
              )}

              {theirHobbies.length > 0 && (
                <Section title="Outside the project">
                  <HobbyGrid hobbies={theirHobbies} />
                </Section>
              )}

              {theirPhotos.length > 0 && (
                <Section title="Photos">
                  <PhotoWall photos={theirPhotos} />
                </Section>
              )}

              {nothingYet && (
                <p className="italic text-[var(--muted)]">
                  {member.full_name} has not added their write-up yet.
                </p>
              )}
            </div>
          </div>
        </article>

        {/* Sticky, like the project page's team column. */}
        <aside className="lg:col-span-4 lg:sticky lg:top-24 lg:self-start xl:col-span-3">
          <MemberSidebar team={team} projects={projects} activeId={member.id} />
        </aside>
      </div>
    </main>
  );
}
