/**
 * A colour per project category, for the sidebar's project list and the cards.
 *
 * Adapted from ../doctor-portfolio/lib/categories.ts, which fixes one accent per
 * known category. Categories here are free text typed in the admin, so known ones
 * keep a fixed colour and any new one gets a stable colour from its name — the
 * same category is the same colour on every page and every visit.
 */

const KNOWN: Record<string, number> = {
  systems: 1, safety: 2, software: 3, web: 4, sensing: 5, data: 6,
};

const PALETTE_SIZE = 8;

export function categoryColor(category: string | null | undefined): string {
  const key = (category ?? "").trim().toLowerCase();
  if (!key) return "var(--cat-8)";
  if (KNOWN[key]) return `var(--cat-${KNOWN[key]})`;
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return `var(--cat-${(hash % PALETTE_SIZE) + 1})`;
}
