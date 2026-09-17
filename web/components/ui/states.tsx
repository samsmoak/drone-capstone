/**
 * The four states every async surface must have.
 *
 * The rule that matters: **a failed fetch must say so, never render nothing.**
 * A blank panel where a battery voltage should be reads as "0" or "fine" to an
 * operator who is about to fly. Silence is the dangerous state.
 */

import type { ReactNode } from "react";

export function LoadingState({ label = "Loading", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div
      className="space-y-3 p-6"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-[var(--surface-2)]"
          style={{ width: `${100 - i * 15}%` }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
      <p className="font-medium text-[var(--foreground)]">{title}</p>
      {hint && <p className="max-w-sm text-sm text-[var(--muted)]">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/**
 * An error the operator can act on.
 *
 * Always says what failed and offers a retry. "Something went wrong" with no
 * recourse is the same as rendering nothing.
 */
export function ErrorState({
  title = "Could not load this",
  detail,
  retry,
}: {
  title?: string;
  detail?: string;
  retry?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-lg border border-[var(--status-critical)] bg-[var(--surface)] p-5"
    >
      <p className="flex items-center gap-2 font-medium text-[var(--foreground)]">
        {/* Icon + text, never colour alone — status colour is not the message. */}
        <span aria-hidden="true">⚠</span>
        {title}
      </p>
      {detail && <p className="text-sm text-[var(--muted)]">{detail}</p>}
      {retry && <div className="mt-2">{retry}</div>}
    </div>
  );
}

/**
 * A figure with its label.
 *
 * The label is muted; **the figure never is**. Grey is for labels, not for a
 * number someone is about to make a decision on.
 */
export function Stat({
  label,
  value,
  unit,
  status,
  hint,
}: {
  label: string;
  value: string | number | null | undefined;
  unit?: string;
  status?: "good" | "warning" | "serious" | "critical";
  hint?: string;
}) {
  // A missing value is stated, not silently rendered as blank or zero.
  const missing = value === null || value === undefined;

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <p className="mt-1 flex items-baseline gap-1">
        <span
          className={`tabular text-2xl font-semibold ${
            missing ? "text-[var(--muted)]" : "text-[var(--foreground)]"
          }`}
        >
          {missing ? "—" : value}
        </span>
        {unit && !missing && (
          <span className="text-sm text-[var(--muted)]">{unit}</span>
        )}
      </p>
      {status && <StatusBadge status={status} />}
      {hint && <p className="mt-1 text-xs text-[var(--muted)]">{hint}</p>}
      {missing && (
        <p className="mt-1 text-xs text-[var(--muted)]">No reading available</p>
      )}
    </div>
  );
}

const STATUS_META = {
  good: { icon: "●", label: "Healthy", color: "var(--status-good)" },
  warning: { icon: "▲", label: "Watch", color: "var(--status-warning)" },
  serious: { icon: "▲", label: "Attention", color: "var(--status-serious)" },
  critical: { icon: "■", label: "Critical", color: "var(--status-critical)" },
} as const;

/**
 * Status always ships icon + label. Colour never carries the meaning alone.
 *
 * `label` overrides the default word. The defaults are crop-health vocabulary
 * ("Healthy", "Watch"); a flight that completed is not "Healthy", so surfaces
 * that reuse the tones for something else say what they mean.
 */
export function StatusBadge({
  status,
  label,
}: {
  status: keyof typeof STATUS_META;
  label?: string;
}) {
  const meta = STATUS_META[status];
  return (
    <span className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium">
      <span aria-hidden="true" style={{ color: meta.color }}>
        {meta.icon}
      </span>
      <span className="text-[var(--foreground)]">{label ?? meta.label}</span>
    </span>
  );
}
