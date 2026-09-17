import Link from "next/link";
import { categoryColor } from "@/lib/categories";
import type { Product } from "@/lib/products";

/**
 * One product, as a card: what it is, where it runs, and what you get.
 *
 * Used by both indexes — /setup (the guide) and /apps (the download) — so the
 * two pages present the same three things in the same order and a reader
 * recognises the second page from the first. The accent is the product's
 * category colour, the same palette the project list uses.
 */
export function ProductCard({
  product,
  href,
  action,
  footer,
}: {
  product: Product;
  href: string;
  /** What the link says. "Setup guide", "Downloads" — the card's own verb. */
  action: string;
  /** A line under the points: availability, size, or what there is instead. */
  footer?: React.ReactNode;
}) {
  const accent = categoryColor(product.category);
  return (
    <article
      style={{ "--accent": accent } as React.CSSProperties}
      className="group relative flex flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-md"
    >
      <span aria-hidden="true" className="h-1.5 w-full bg-[var(--accent)]" />
      <div className="flex flex-1 flex-col p-6">
        <p className="eyebrow flex items-center gap-1.5">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
          {product.runsOn}
        </p>

        <h2 className="font-display mt-3 text-xl font-semibold tracking-tight">
          {/* The whole card is the link: one target, and the heading still
              carries it for anyone tabbing through. */}
          <Link href={href} className="after:absolute after:inset-0 group-hover:text-[var(--heading)]">
            {product.name}
          </Link>
        </h2>

        <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{product.summary}</p>

        <ul className="mt-4 mb-5 grid gap-1.5">
          {product.points.map((point) => (
            <li key={point} className="flex gap-2 text-sm leading-relaxed">
              <span aria-hidden="true" className="text-[var(--accent)]">▸</span>
              <span>{point}</span>
            </li>
          ))}
        </ul>

        {/* mt-auto: the cards are the same height in the grid, so the links line
            up across them instead of following each card's own text. */}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-4">
          <span className="text-sm font-semibold text-[var(--heading)] underline-offset-4 group-hover:underline">
            {action} →
          </span>
          {footer && <span className="tabular text-xs text-[var(--muted)]">{footer}</span>}
        </div>
      </div>
    </article>
  );
}
