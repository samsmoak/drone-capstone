// Shared (client + server) helpers for BlockNote document JSON.

export type TocSection = { id: string; title: string; level: number };

type InlineNode = { type?: string; text?: string };
type BlockNode = {
  type?: string;
  props?: { level?: number };
  content?: InlineNode[] | unknown;
};

function inlineText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .map((n) => (n && typeof n === "object" && "text" in n ? String((n as InlineNode).text ?? "") : ""))
    .join("")
    .trim();
}

function slugBase(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-") || "section"
  );
}

/** Ordered list of heading sections for the table of contents. Slugs are made
 *  unique with a numeric suffix on collision so TOC anchors are stable. */
export function extractSections(blocks: unknown): TocSection[] {
  if (!Array.isArray(blocks)) return [];
  const sections: TocSection[] = [];
  const seen = new Map<string, number>();

  for (const raw of blocks as BlockNode[]) {
    if (!raw || raw.type !== "heading") continue;
    const title = inlineText(raw.content);
    if (!title) continue;
    const level = raw.props?.level ?? 2;
    let slug = slugBase(title);
    const count = seen.get(slug) ?? 0;
    seen.set(slug, count + 1);
    if (count > 0) slug = `${slug}-${count + 1}`;
    sections.push({ id: slug, title, level });
  }
  return sections;
}
