/**
 * Number fields for the editor: metres and seconds, typed exactly.
 *
 * A field keeps its own text while it is being typed in and commits on blur or
 * Enter. Committing on every keystroke would clamp "-" or "0." out from under
 * the operator mid-number. On commit the value goes through the caller's
 * clamp — the room's map — and the field shows what was actually kept, so a
 * number that was too big visibly becomes the largest allowed.
 */

import { useEffect, useId, useState } from "react";
import { formatMetres } from "@/lib/format";

export function NumberField({
  label, value, onCommit, unit = "m", step = 0.05, min, max, hint, width = "w-24",
}: {
  label: string;
  value: number;
  onCommit: (value: number) => void;
  unit?: "m" | "s";
  step?: number;
  min?: number;
  max?: number;
  /** Shown under the field — the limit it is held to, say. */
  hint?: string;
  width?: string;
}) {
  const id = useId();
  const [text, setText] = useState(value.toFixed(2));
  // A drag on the canvas changes the value from outside: follow it.
  useEffect(() => setText(value.toFixed(2)), [value]);

  const commit = () => {
    const parsed = Number.parseFloat(text);
    if (!Number.isFinite(parsed)) {
      setText(value.toFixed(2));
      return;
    }
    const kept = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, parsed));
    onCommit(kept);
    setText(kept.toFixed(2));
  };

  return (
    <label htmlFor={id} className="grid content-start gap-1 text-xs">
      <span className="eyebrow">{label}</span>
      <span className="flex items-center gap-1">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          max={max}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
          className={`mono min-h-9 ${width} border border-[var(--border)] bg-[var(--surface-2)] px-2 text-sm`}
        />
        <span className="text-[var(--muted)]">{unit}</span>
      </span>
      {hint !== undefined
        ? <span className="text-[var(--muted)]">{hint}</span>
        : unit === "m" && <span className="text-[var(--muted)]">{formatMetres(value)}</span>}
    </label>
  );
}

export function TextField({ label, value, onChange, placeholder, width = "w-full" }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  width?: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="grid content-start gap-1 text-xs">
      <span className="eyebrow">{label}</span>
      <input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`min-h-9 ${width} border border-[var(--border)] bg-[var(--surface-2)] px-2 text-sm`}
      />
    </label>
  );
}

/** A small secondary action inside a panel: 32 px, like the action rail's. */
export function SmallButton({ children, onClick, disabled, pressed, title, tone = "normal" }: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
  title?: string;
  tone?: "normal" | "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-pressed={pressed}
      className={`inline-flex min-h-8 items-center justify-center gap-1 border px-2.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
        pressed
          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
          : tone === "danger"
            // The border carries the warning; the text stays --foreground, whose
            // contrast is measured, rather than a status colour that is not.
            ? "border-[var(--status-critical)] text-[var(--foreground)]"
            : "border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--surface-2)]"
      }`}
    >
      {children}
    </button>
  );
}
