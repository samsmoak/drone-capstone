import { SITE_CONTAINER } from "@/lib/layout";
import type { Metadata } from "next";
import { TeamCard } from "@/components/portfolio/TeamCard";
import { PageIntro } from "@/components/site/PageIntro";
import { getPageContent, getTeamMembers } from "@/lib/queries";

export const metadata: Metadata = {
  title: "Team",
  description: "The people who built CropWatcher.",
};

export default async function TeamPage() {
  const [team, intro] = await Promise.all([getTeamMembers(), getPageContent("team")]);

  return (
    <main className={`${SITE_CONTAINER} py-16 md:py-20`}>
      <PageIntro content={intro} />

      {team.length === 0 ? (
        <div className="mt-16 rounded-xl border border-dashed border-[var(--border)] p-16 text-center">
          <p className="text-[var(--muted)]">The team has not been added yet.</p>
        </div>
      ) : (
        <div className="mt-12 grid grid-cols-2 gap-x-6 gap-y-12 sm:grid-cols-3 lg:grid-cols-5">
          {team.map((member) => <TeamCard key={member.id} member={member} />)}
        </div>
      )}
    </main>
  );
}
