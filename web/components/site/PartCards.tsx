import Image from "next/image";
import Link from "next/link";
import { text, type ContentObject } from "@/lib/site-content";

/**
 * The six parts of DroneDeck as cards: photo, status tag, title, text, and a
 * link to the part's write-up. One source — the home page's "Part cards"
 * field (/admin/pages/home) — drawn on the home page and on /projects, so the
 * two can never list different parts.
 */
export function PartCards({ parts, className = "" }: { parts: ContentObject[]; className?: string }) {
  return (
    <ul className={`grid gap-4 sm:grid-cols-2 lg:grid-cols-3 ${className}`}>
      {parts.map((item, i) => (
        <li key={`${text(item, "title")}-${i}`}>
          <PartCard item={item} />
        </li>
      ))}
    </ul>
  );
}

/** One of the six parts: photo, status tag, title, text — a link when it has one. */
function PartCard({ item }: { item: ContentObject }) {
  const image = text(item, "image");
  const href = text(item, "href");
  const body = (
    <article className="flex h-full flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] transition-colors group-hover:border-[var(--heading)]">
      {image && (
        <div className="relative aspect-[16/10] bg-[var(--surface-2)]">
          <Image src={image} alt="" fill sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw" className="object-cover" />
        </div>
      )}
      <div className="flex flex-1 flex-col p-6">
        {text(item, "status") && <StatusTag status={text(item, "status")} className="self-start" />}
        <h3 className="font-display mt-3 text-lg font-semibold group-hover:text-[var(--heading)]">{text(item, "title")}</h3>
        <p className="mt-2 flex-1 text-sm leading-relaxed text-[var(--muted)]">{text(item, "body")}</p>
        {href && <p className="mt-4 text-sm font-medium text-[var(--heading)]">Read how it is built →</p>}
      </div>
    </article>
  );
  return href
    ? <Link href={href} className="group block h-full rounded-xl">{body}</Link>
    : <div className="h-full">{body}</div>;
}

/**
 * A status as a tag: the word always, a coloured dot beside it. The colour is
 * never the only signal (WCAG 1.4.1), and the text stays the ink colour, so no
 * status hue has to clear 4.5:1 as text.
 */
export function StatusTag({ status, className = "" }: { status: string; className?: string }) {
  const key = status.trim().toLowerCase();
  const tone =
    key === "built" || key === "done" ? "var(--status-good)"
      : key === "in progress" || key === "now" ? "var(--status-warning)"
      : "var(--axis)";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-2.5 py-0.5 text-xs font-medium ${className}`}>
      <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ background: tone }} />
      {status}
    </span>
  );
}
