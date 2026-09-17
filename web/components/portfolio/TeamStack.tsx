"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { categoryColor } from "@/lib/categories";
import type { TeamMemberRow } from "@/lib/queries";

function Avatar({ member, size }: { member: TeamMemberRow; size: number }) {
  return (
    <span className="relative block shrink-0 overflow-hidden rounded-full ring-2 ring-[var(--surface)]"
          style={{
            width: size,
            height: size,
            // A soft tint per person, so a row of initials is not a row of grey.
            background: `color-mix(in srgb, ${categoryColor(member.full_name)} 22%, var(--surface))`,
          }}>
      {member.avatar_url ? (
        <Image src={member.avatar_url} alt="" fill sizes={`${size}px`} className="object-cover" />
      ) : (
        <span className="font-display flex h-full w-full items-center justify-center font-semibold text-[var(--foreground)]"
              style={{ fontSize: size * 0.42 }}>
          {member.full_name.trim().charAt(0).toUpperCase()}
        </span>
      )}
    </span>
  );
}

/** One person, laid out as a row: photo, name, role, and their links. */
function MemberRow({ member }: { member: TeamMemberRow }) {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3.5">
      <Avatar member={member} size={52} />
      <div className="min-w-0">
        <p className="font-display truncate text-[15px] font-semibold">{member.full_name}</p>
        {member.role && <p className="truncate text-xs text-[var(--muted)]">{member.role}</p>}
        {member.website_url && (
          <a href={member.website_url} target="_blank" rel="noopener noreferrer"
             className="mt-0.5 block truncate text-xs font-medium text-[var(--heading)] underline-offset-2 hover:underline">
            {member.website_url.replace(/^https?:\/\//, "").replace(/\/$/, "")}
          </a>
        )}
        {member.email && (
          <a href={`mailto:${member.email}`} className="block truncate text-xs text-[var(--muted)] hover:underline">
            {member.email}
          </a>
        )}
      </div>
    </div>
  );
}

/**
 * The project's team as a stack of cards.
 *
 * Closed, the first cards sit stacked on top of each other, so the sidebar stays
 * short enough to stay in view while you read. Open, every card fans out in a
 * panel that floats over the project list below — the page underneath does not
 * move — and closes again from the stack, Escape or a click elsewhere.
 */
export function TeamStack({ team }: { team: TeamMemberRow[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); toggle.current?.focus(); } };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onClick); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const deck = team.slice(0, 3);

  return (
    <div ref={root} className="relative">
      <button
        ref={toggle}
        type="button"
        aria-expanded={open}
        aria-controls="team-panel"
        onClick={() => setOpen((v) => !v)}
        className="group block w-full rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 text-left shadow-sm transition-shadow hover:shadow-md"
      >
        <span className="flex items-center justify-between gap-3">
          <span>
            <span className="eyebrow block">The team</span>
            <span className="mt-1 block text-sm text-[var(--muted)]">
              {team.length} {team.length === 1 ? "person" : "people"}
            </span>
          </span>
          <span className="flex -space-x-3">
            {team.slice(0, 5).map((m) => <Avatar key={m.id} member={m} size={34} />)}
          </span>
        </span>

        {/* The deck: each card behind the one in front, slightly smaller and lower. */}
        <span className="relative mt-4 block" style={{ height: 76 + (deck.length - 1) * 12 }}>
          {deck.map((member, i) => (
            <span
              key={member.id}
              className="absolute inset-x-0 top-0 block transition-transform duration-300 ease-out motion-reduce:transition-none group-hover:-translate-y-0.5"
              style={{
                transform: `translateY(${i * 12}px) scale(${1 - i * 0.06})`,
                zIndex: deck.length - i,
                opacity: 1 - i * 0.15,
              }}
            >
              <span className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 shadow-sm">
                <Avatar member={member} size={44} />
                <span className="min-w-0">
                  <span className="font-display block truncate text-sm font-semibold">{member.full_name}</span>
                  {member.role && <span className="block truncate text-xs text-[var(--muted)]">{member.role}</span>}
                </span>
              </span>
            </span>
          ))}
        </span>

        <span className="mt-3 flex items-center justify-center gap-1.5 text-xs font-semibold text-[var(--heading)]">
          {open ? "Close" : "Show everyone"}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden="true"
               className={`h-3.5 w-3.5 transition-transform duration-300 ${open ? "rotate-180" : ""}`}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6" />
          </svg>
        </span>
      </button>

      {open && (
        <div
          id="team-panel"
          className="animate-[team-in_220ms_ease-out] absolute inset-x-0 top-full z-40 mt-2 max-h-[70vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-3 shadow-2xl motion-reduce:animate-none"
        >
          <ul className="grid gap-2.5">
            {team.map((member) => (
              <li key={member.id}><MemberRow member={member} /></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
