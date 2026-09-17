import Image from "next/image";
import type { Hobby } from "@/lib/team-profile";

/**
 * What someone does outside the project: a card each, photo on top.
 *
 * Adapted from ../doctor-portfolio/components/public/InterestGrid.tsx. That one
 * is a client component that opens each interest in a modal; here the whole
 * write-up is short enough to sit on the card, so this stays a server component
 * — no JavaScript to read someone's hobbies.
 */
export function HobbyGrid({ hobbies }: { hobbies: Hobby[] }) {
  if (hobbies.length === 0) return null;
  return (
    <ul className="grid gap-5 sm:grid-cols-2">
      {hobbies.map((hobby, i) => (
        <li
          key={`${hobby.title}-${i}`}
          className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)]"
        >
          {hobby.image_url && (
            <div className="relative aspect-[16/10] bg-[var(--surface-2)]">
              <Image
                src={hobby.image_url}
                alt=""
                fill
                sizes="(max-width: 640px) 100vw, 40vw"
                className="object-cover"
              />
            </div>
          )}
          <div className="p-5">
            {hobby.title && <h3 className="font-display text-lg font-semibold">{hobby.title}</h3>}
            {hobby.body && (
              <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{hobby.body}</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
