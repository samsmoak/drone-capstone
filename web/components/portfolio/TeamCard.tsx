import Image from "next/image";
import type { TeamMemberRow } from "@/lib/queries";

/**
 * One person: photo, name, and — below the card, as asked — their website and
 * email when they have them. Nothing is shown for a link that does not exist.
 */
export function TeamCard({ member, compact = false }: { member: TeamMemberRow; compact?: boolean }) {
  const initial = member.full_name.trim().charAt(0).toUpperCase();
  return (
    <article className="flex flex-col items-center text-center">
      <div
        className={`relative overflow-hidden rounded-xl bg-[var(--surface-2)] ring-1 ring-[var(--border)] ${
          compact ? "h-24 w-24" : "aspect-square w-full max-w-56"
        }`}
      >
        {member.avatar_url ? (
          <Image
            src={member.avatar_url}
            alt={`Photo of ${member.full_name}`}
            fill
            sizes={compact ? "96px" : "224px"}
            className="object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <span className={`font-display text-[var(--heading)] ${compact ? "text-3xl" : "text-5xl"}`}>
              {initial}
            </span>
          </div>
        )}
      </div>
      <h3 className={`font-display mt-3 font-semibold ${compact ? "text-base" : "text-lg"}`}>
        {member.full_name}
      </h3>
      {member.role && <p className="text-sm text-[var(--muted)]">{member.role}</p>}
      {(member.website_url || member.email) && (
        <div className="mt-2 grid gap-0.5 text-sm">
          {member.website_url && (
            <a
              href={member.website_url}
              target="_blank"
              rel="noopener noreferrer"
              className="wrap-anywhere font-medium text-[var(--heading)] underline-offset-4 hover:underline"
            >
              {member.website_url.replace(/^https?:\/\//, "").replace(/\/$/, "")}
            </a>
          )}
          {member.email && (
            <a
              href={`mailto:${member.email}`}
              className="wrap-anywhere text-[var(--muted)] underline-offset-4 hover:text-[var(--foreground)] hover:underline"
            >
              {member.email}
            </a>
          )}
        </div>
      )}
    </article>
  );
}
