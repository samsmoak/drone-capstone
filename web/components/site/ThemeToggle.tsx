"use client";

import { useSyncExternalStore } from "react";
import { applyTheme, currentTheme, subscribeTheme, type Theme } from "@/lib/theme";

/**
 * One button: switches light ↔ dark and remembers the choice (lib/theme.ts).
 *
 * The icon shows the theme you would switch TO, as a light switch shows the
 * other position. On the server the theme is unknown, so the button renders
 * with no icon there rather than guessing and flipping after load.
 */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const theme = useSyncExternalStore<Theme | null>(subscribeTheme, currentTheme, () => null);

  const next: Theme = theme === "dark" ? "light" : "dark";
  const label = theme ? `Switch to ${next} mode` : "Switch colour theme";

  return (
    <button
      type="button"
      onClick={() => applyTheme(next)}
      aria-label={label}
      title={label}
      className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)] ${className}`}
    >
      {theme === "dark" && <SunIcon />}
      {theme === "light" && <MoonIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path strokeLinecap="round" d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" />
    </svg>
  );
}
