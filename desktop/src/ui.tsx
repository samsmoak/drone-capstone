/**
 * The small pieces every window is built from.
 *
 * Copy-adapted from `web/components/ui/states.tsx` so the desktop app and the
 * dashboard are recognisably one product. The rules come with them:
 *
 * - **The label is muted; the figure never is.** Grey is for labels, not for a
 *   number someone is about to make a decision on.
 * - **A missing value is stated, not rendered as blank or zero.** A blank panel
 *   where a battery voltage belongs reads as "fine" to an operator about to fly.
 * - **Status ships icon + words.** Colour never carries the meaning alone.
 */

import type { ReactNode } from "react";

export type Tone = "good" | "warning" | "serious" | "critical" | "idle";

const TONE_ICON: Record<Tone, string> = {
  good: "●", warning: "▲", serious: "▲", critical: "■", idle: "○",
};

const TONE_COLOR: Record<Tone, string> = {
  good: "var(--status-good)",
  warning: "var(--status-warning)",
  serious: "var(--status-serious)",
  critical: "var(--status-critical)",
  idle: "var(--muted)",
};

export function StatusDot({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" style={{ color: TONE_COLOR[tone] }}>{TONE_ICON[tone]}</span>
      <span>{children}</span>
    </span>
  );
}

export function Stat({
  label, value, unit, tone, hint, digits = 2,
}: {
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  tone?: Tone;
  hint?: string;
  digits?: number;
}) {
  const missing = value === null || value === undefined || value === "";
  const shown = typeof value === "number" ? value.toFixed(digits) : value;
  // Text values are things like an email or a hardware id: they get a smaller
  // size and break anywhere, because a 1000 px window is not the only width
  // this runs at and an overflowing figure is an unreadable one.
  const isText = typeof value === "string";

  return (
    <div className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <p className="eyebrow">{label}</p>
      <p className="mt-2 flex flex-wrap items-baseline gap-x-1">
        <span
          className={`font-semibold ${
            isText ? "text-lg wrap-anywhere" : "tabular text-2xl"
          } ${missing ? "text-[var(--muted)]" : "text-[var(--foreground)]"}`}
        >
          {missing ? "—" : shown}
        </span>
        {unit && !missing && <span className="text-sm text-[var(--muted)]">{unit}</span>}
      </p>
      {tone && (
        <p className="mt-2 text-xs font-medium">
          <StatusDot tone={tone}>{hint ?? ""}</StatusDot>
        </p>
      )}
      {!tone && hint && <p className="mt-1 text-xs text-[var(--muted)]">{hint}</p>}
      {missing && !hint && (
        <p className="mt-1 text-xs text-[var(--muted)]">Not available on this drone</p>
      )}
    </div>
  );
}

/**
 * The title of whichever page is showing.
 *
 * Every page carries one, in the same place and the same colour, so the window
 * always answers "where am I" without the operator reading the nav back.
 */
export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="grid gap-2">
      <h1 className="font-display wrap-anywhere text-3xl font-semibold leading-tight text-[var(--heading)]">
        {title}
      </h1>
      {children && <p className="max-w-2xl text-[15px] leading-relaxed text-[var(--muted)]">{children}</p>}
    </header>
  );
}

export function Panel({
  title, children, action, note,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  note?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-4">
        {/* The rule is decorative (it carries no meaning colour has to convey);
            the title's own colour is the measured --heading token. */}
        <h2 className="flex min-w-0 items-center gap-2.5 text-lg font-semibold tracking-tight text-[var(--heading)]">
          <span aria-hidden="true" className="h-4 w-1 shrink-0 rounded-full bg-[var(--primary)]" />
          {title}
        </h2>
        {action}
      </div>
      {note && <p className="mb-5 max-w-3xl text-sm leading-relaxed text-[var(--muted)]">{note}</p>}
      {children}
    </section>
  );
}

export function Button({
  children, onClick, variant = "secondary", disabled, type = "button", title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
}) {
  const styles = {
    primary: "bg-[var(--primary)] text-[var(--on-primary)] border-transparent",
    secondary: "border-[var(--border)] text-[var(--foreground)]",
    danger: "border-[var(--status-critical)] bg-[var(--status-critical)] text-[var(--on-critical)] font-bold",
  }[variant];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-5 text-sm font-medium disabled:opacity-50 ${styles}`}
    >
      {children}
    </button>
  );
}

/** An error the operator can act on. Never "something went wrong" alone. */
export function Message({ text, tone }: { text: string; tone: Tone }) {
  return (
    <p
      role={tone === "critical" ? "alert" : "status"}
      className="rounded-lg border bg-[var(--surface)] px-4 py-3 text-sm"
      style={{ borderColor: TONE_COLOR[tone] }}
    >
      <StatusDot tone={tone}>{text}</StatusDot>
    </p>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <p role="status" aria-live="polite" className="flex items-center gap-3 text-sm">
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--primary)]"
      />
      {label}
    </p>
  );
}
