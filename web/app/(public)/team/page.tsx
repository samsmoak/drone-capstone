import type { Metadata } from "next";
import { TeamCard } from "@/components/portfolio/TeamCard";
import { getTeamMembers } from "@/lib/queries";

export const metadata: Metadata = {
  title: "Team",
  description: "The people who built CropWatcher.",
};

export default async function TeamPage() {
  const team = await getTeamMembers();

  return (
    <main className="mx-auto max-w-6xl px-6 py-16 md:py-20">
      <p className="eyebrow text-[var(--heading)]">Capstone team</p>
      <h1 className="font-display mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">The team</h1>
      <p className="mt-4 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">
        The people who designed, built and flew CropWatcher.
      </p>

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
