"use client";

import { forwardRef } from "react";

/** Form primitives for the admin. Copied from ../doctor-portfolio, this site's tokens. */

export function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="eyebrow mb-1.5 block">
      {children}
    </label>
  );
}

const baseField =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2.5 text-sm outline-none transition-colors placeholder:text-[var(--muted)] focus:border-[var(--primary)]";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input(props, ref) {
    return <input ref={ref} {...props} className={`${baseField} ${props.className ?? ""}`} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea(props, ref) {
    return <textarea ref={ref} {...props} className={`${baseField} resize-y leading-relaxed ${props.className ?? ""}`} />;
  },
);

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger";
};

export function Button({ variant = "primary", className = "", type = "button", ...props }: ButtonProps) {
  const variants: Record<string, string> = {
    primary: "bg-[var(--primary)] text-[var(--on-primary)] hover:opacity-90",
    outline: "border border-[var(--border)] hover:border-[var(--primary)]",
    ghost: "text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]",
    danger: "text-[var(--status-critical)] hover:bg-[var(--surface-2)]",
  };
  return (
    <button
      type={type}
      {...props}
      className={`inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    />
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-[var(--border)] bg-[var(--surface)] ${className}`}>{children}</div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const published = status === "published";
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
        published ? "border-[var(--status-good)]" : "border-[var(--border)] text-[var(--muted)]"
      }`}
    >
      {published ? "● Published" : "○ Draft"}
    </span>
  );
}
