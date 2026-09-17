import Image from "next/image";
import Link from "next/link";
import type { TeamMemberRow } from "@/lib/queries";
import { memberPath } from "@/lib/routes";

/**
 * One person: photo, name, role — and, when they have a page, the whole card is
 * the way into it. Their website and email sit below the link rather than
 * inside it, because a link inside a link is not a link.
 */
export function TeamCard({ member, compact = false }: { member: TeamMemberRow; compact?: boolean }) {
  const initial = member.full_name.trim().charAt(0).toUpperCase();

  const face = (
    <>
      <div
        className={`relative overflow-hidden rounded-xl bg-[var(--surface-2)] ring-1 ring-[var(--border)] transition-[transform,box-shadow] duration-200 group-hover:-translate-y-0.5 group-hover:shadow-md ${
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
      <h3
        className={`font-display mt-3 font-semibold group-hover:text-[var(--heading)] ${
          compact ? "text-base" : "text-lg"
        }`}
      >
        {member.full_name}
      </h3>
      {member.role && <p className="text-sm text-[var(--muted)]">{member.role}</p>}
    </>
  );

  return (
    <article className="flex w-full flex-col items-center text-center">
      {member.slug ? (
        <Link
          href={memberPath(member.slug)}
          className="group flex w-full flex-col items-center rounded-xl focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--heading)]"
        >
          {face}
          <span className="mt-1 text-xs font-medium text-[var(--heading)] underline-offset-4 group-hover:underline">
            View profile
          </span>
        </Link>
      ) : (
        <div className="group flex w-full flex-col items-center">{face}</div>
      )}

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
