"use client";

import { useMemo, useState } from "react";
import type { AlbumCard as AlbumCardData } from "@/lib/queries";
import { AlbumCard } from "./AlbumCard";

/** The album grid, with a filter by category. "All" keeps every album in view. */
export function AlbumGrid({ albums }: { albums: AlbumCardData[] }) {
  const categories = useMemo(
    () => Array.from(new Set(albums.map((a) => a.category).filter(Boolean))),
    [albums],
  );
  const [active, setActive] = useState<string | null>(null);
  const shown = active ? albums.filter((a) => a.category === active) : albums;

  return (
    <>
      {categories.length > 1 && (
        <div role="group" aria-label="Filter albums" className="mt-10 flex flex-wrap gap-2">
          {[null, ...categories].map((c) => {
            const selected = active === c;
            return (
              <button
                key={c ?? "all"}
                type="button"
                aria-pressed={selected}
                onClick={() => setActive(c)}
                className={`min-h-10 rounded-full border px-4 text-sm font-medium transition-colors ${
                  selected
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
                    : "border-[var(--border)] hover:border-[var(--primary)]"
                }`}
              >
                {c ?? "All"}
              </button>
            );
          })}
        </div>
      )}
      <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {shown.map((album, i) => <AlbumCard key={album.id} album={album} priority={i < 3} />)}
      </div>
    </>
  );
}
