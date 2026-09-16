import type { ReactNode } from "react";

/**
 * The heading block every operator page opens with.
 *
 * Extracted once six pages needed it rather than on the second — the dashboard
 * wrote it inline first, and that copy stays as it is because it carries a
 * date subtitle none of the others do.
 *
 * The action sits top-right on every page, so the primary control is in the
 * same place whichever surface you are on.
 */
export function PageHeader({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-1 max-w-2xl text-sm text-[var(--muted)]">{description}</p>
        )}
      </div>
      {action}
    </header>
  );
}
