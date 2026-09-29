/**
 * One object's card in the editor's form: the room, an obstacle, a point, the
 * start — framed on all four sides so it reads as a thing, and framed in
 * --primary, two pixels, all four sides, while it is the selected one.
 *
 * ONLY THE SELECTED OBJECT CHANGES. Its fields are editable; every other
 * card's fields show their numbers read-only (fields.tsx). Touching a card
 * that is not selected SELECTS it — and that first click does only that: a
 * checkbox does not toggle, Remove does not remove, until the object is the
 * selected one. A field that is clicked or tabbed into selects its object and
 * is editable straight away, so typing never needs two steps.
 *
 * Nothing selected (a click on empty floor, or anywhere in the form outside a
 * card — MissionEditor) means every object is shown equally, on the map and
 * here, and none of them can be changed until one is picked.
 */

import { useEffect, useRef, type ReactNode } from "react";

/** Marks a card, so a click outside every card can clear the selection. */
export const CARD_ATTR = "data-object-card";

export function ObjectCard({ selected, flagged = false, onSelect, label, as = "li", children, className = "" }: {
  selected: boolean;
  /** The agent reports a problem with it: a red frame while not selected. */
  flagged?: boolean;
  onSelect: () => void;
  /** What it is, for a screen reader: "Obstacle Bench", "The room". */
  label: string;
  as?: "li" | "section";
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  // The click that selected this card is the only thing it does.
  const swallow = useRef(false);

  // Selected from the map: bring the card into view, unless the form itself
  // did the selecting (focus is already in it).
  useEffect(() => {
    if (!selected || !ref.current) return;
    if (ref.current.contains(document.activeElement)) return;
    ref.current.scrollIntoView({ block: "nearest",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [selected]);

  const Tag = as;
  return (
    <Tag
      ref={ref as never}
      {...{ [CARD_ATTR]: "" }}
      aria-label={`${label}${selected ? " — selected" : ""}`}
      aria-current={selected || undefined}
      onPointerDownCapture={(e) => {
        if (selected || e.button !== 0) return;
        swallow.current = true;
        onSelect();
      }}
      onClickCapture={(e) => {
        if (!swallow.current) return;
        swallow.current = false;
        // Text and number fields take focus on pointer-down, before this,
        // and are editable once their object is selected — let them be.
        const target = e.target as HTMLElement;
        if (target.matches("input[type=number], input[type=text], input:not([type])")) return;
        e.preventDefault();
        e.stopPropagation();
      }}
      onFocusCapture={() => { if (!selected) onSelect(); }}
      // A 1 px frame in --muted (measured 7.27:1 on --surface-2 light, 8.03:1
      // dark — it clearly reads as a thing), and 2 px of --primary on all
      // four sides when selected (6.07:1 light, 3.95:1 dark — both over the
      // 3:1 a non-text boundary needs). The padding gives back the extra pixel, so
      // selecting never shifts a card's contents.
      className={`grid gap-2 bg-[var(--surface-2)] ${
        selected ? "border-2 border-[var(--primary)] p-[9px]"
        : flagged ? "border-2 border-[var(--status-critical)] p-[9px]"
        : "border border-[var(--muted)] p-[10px] hover:border-[var(--foreground)]"} ${className}`}
    >
      {children}
    </Tag>
  );
}

/** The corner tag: "Selected", or what a click will do. */
export function CardState({ selected }: { selected: boolean }) {
  return selected
    ? <span className="mono text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--heading)]">Selected</span>
    : <span className="text-[10px] text-[var(--muted)]">Click to select and edit</span>;
}
