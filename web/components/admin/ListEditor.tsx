"use client";

import { Button, Card } from "./ui";

/**
 * A list of things that can be added, reordered and removed — the hobbies,
 * links and photos on a team member's page.
 *
 * PageEditor has the same three controls, driven by a field spec, for the
 * wording of a whole page. This one takes the row's fields as a render prop
 * instead, because a hobby's editor is a photo picker beside two text boxes,
 * which no spec of text/textarea fields can draw. Third use of this pattern is
 * the point to unify them.
 */
export function ListEditor<T>({
  label,
  items,
  onChange,
  blank,
  addLabel,
  limit,
  children,
}: {
  label: string;
  items: T[];
  onChange: (next: T[]) => void;
  blank: () => T;
  addLabel: string;
  limit: number;
  /** Draws one row. `set` replaces this row with an edited copy. */
  children: (item: T, set: (next: T) => void, index: number) => React.ReactNode;
}) {
  function move(index: number, dir: -1 | 1) {
    const target = index + dir;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="eyebrow">{label}</h3>
        <span className="text-xs text-[var(--muted)]">
          {items.length} of {limit}
        </span>
      </div>

      {items.length === 0 && (
        <p className="rounded-lg border border-dashed border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--muted)]">
          Nothing here yet. This section is left off the page until something is added.
        </p>
      )}

      <ul className="grid gap-3">
        {items.map((item, i) => (
          <li key={i}>
            <Card className="grid gap-4 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="eyebrow">
                  {label.replace(/s$/, "")} {i + 1}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    onClick={() => move(i, -1)}
                    disabled={i === 0}
                    aria-label={`Move ${label.toLowerCase()} ${i + 1} up`}
                  >
                    ▲
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => move(i, 1)}
                    disabled={i === items.length - 1}
                    aria-label={`Move ${label.toLowerCase()} ${i + 1} down`}
                  >
                    ▼
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => onChange(items.filter((_, j) => j !== i))}
                    aria-label={`Remove ${label.toLowerCase()} ${i + 1}`}
                  >
                    Remove
                  </Button>
                </div>
              </div>
              {children(item, (next) => onChange(items.map((it, j) => (j === i ? next : it))), i)}
            </Card>
          </li>
        ))}
      </ul>

      <div>
        <Button variant="outline" onClick={() => onChange([...items, blank()])} disabled={items.length >= limit}>
          {items.length >= limit ? `That is the limit of ${limit}` : addLabel}
        </Button>
      </div>
    </section>
  );
}
