import { text, type ContentObject } from "@/lib/site-content";

/** The eyebrow, title and introduction that open a visitor page. */
export function PageIntro({ content, className = "" }: { content: ContentObject; className?: string }) {
  const eyebrow = text(content, "eyebrow");
  const intro = text(content, "intro");
  return (
    <header className={className}>
      {eyebrow && <p className="eyebrow text-[var(--heading)]">{eyebrow}</p>}
      <h1 className="font-display mt-3 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
        {text(content, "title")}
      </h1>
      {intro && <p className="mt-4 max-w-2xl text-lg leading-relaxed text-[var(--muted)]">{intro}</p>}
    </header>
  );
}
