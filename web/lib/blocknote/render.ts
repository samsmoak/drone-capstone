import "server-only";
import { ServerBlockNoteEditor } from "@blocknote/server-util";
import { extractSections, type TocSection } from "./content";

export type RenderedContent = { html: string; sections: TocSection[] };

/** Inject stable TOC ids onto the rendered heading tags, in document order. */
function injectHeadingIds(html: string, sections: TocSection[]): string {
  let i = 0;
  return html.replace(/<h([1-6])(\s|>)/g, (match, level, tail) => {
    const section = sections[i];
    i += 1;
    if (!section) return match;
    return `<h${level} id="${section.id}"${tail === ">" ? ">" : tail}`;
  });
}

/**
 * Give every table its own horizontal scroller. A story table is six columns
 * wide; on a 390 px phone it pushed the whole page 177 px sideways
 * (2026-09-28). Now the table scrolls inside its box and the page does not.
 * The wrapper is a focusable, labelled region so a keyboard can scroll it too
 * (WCAG 2.1.1).
 */
function scrollableTables(html: string): string {
  return html
    .replace(/<table/g, '<div class="prose-table" role="region" aria-label="Table" tabindex="0"><table')
    .replace(/<\/table>/g, "</table></div>");
}

/** Render a stored BlockNote document to themed static HTML for a public page. */
export async function renderProjectContent(
  blocks: unknown,
): Promise<RenderedContent> {
  const sections = extractSections(blocks);
  const list = Array.isArray(blocks) ? blocks : [];
  if (list.length === 0) return { html: "", sections };

  const editor = ServerBlockNoteEditor.create();
  // Lossy export = clean semantic HTML (<h2>, <p>, <ul>, <figure>, <table>,
  // <blockquote>) that we style with our own bespoke prose theme for full
  // consistency with the site — rather than shipping the editor's own CSS.
  const raw = await editor.blocksToHTMLLossy(
    list as Parameters<typeof editor.blocksToHTMLLossy>[0],
  );
  return { html: scrollableTables(injectHeadingIds(raw, sections)), sections };
}
