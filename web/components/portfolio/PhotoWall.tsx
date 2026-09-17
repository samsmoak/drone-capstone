import Image from "next/image";
import type { Photo } from "@/lib/team-profile";

/**
 * Someone's own photos. A caption is optional; where there is one it sits under
 * the photo rather than over it, so it is readable whatever the photo is.
 *
 * The first photo is wide and the rest are square — a grid of identical squares
 * reads as a contact sheet, which is not what a person's page is for.
 */
export function PhotoWall({ photos }: { photos: Photo[] }) {
  if (photos.length === 0) return null;
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3">
      {photos.map((photo, i) => (
        <li key={`${photo.url}-${i}`} className={i === 0 && photos.length > 2 ? "col-span-2 row-span-2" : ""}>
          <figure className="h-full">
            <div
              className={`relative overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-2)] ${
                i === 0 && photos.length > 2 ? "aspect-[4/3]" : "aspect-square"
              }`}
            >
              <Image
                src={photo.url}
                alt={photo.caption || ""}
                fill
                sizes="(max-width: 640px) 50vw, 30vw"
                className="object-cover"
              />
            </div>
            {photo.caption && (
              <figcaption className="mt-2 text-xs leading-relaxed text-[var(--muted)]">
                {photo.caption}
              </figcaption>
            )}
          </figure>
        </li>
      ))}
    </ul>
  );
}
