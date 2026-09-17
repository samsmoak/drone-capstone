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
  return { html: injectHeadingIds(raw, sections), sections };
}
