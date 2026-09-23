/**
 * Whether a CSS media query currently matches, as state.
 *
 * Needed because Control's two columns are not the same TREE at every width,
 * only the same content: side by side they are a draggable split, and stacked
 * they are two blocks in the page's own scroll with the controls first. A
 * breakpoint class cannot express that — a splitter has to know whether it is
 * splitting anything.
 */

import { useEffect, useState } from "react";

/** Tailwind's `lg`. Below it Control stacks and there is nothing to split. */
export const WIDE = "(min-width: 1024px)";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);

  return matches;
}
