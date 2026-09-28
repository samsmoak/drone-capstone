// PARITY: web/components/site/ThemeToggle.tsx — same behaviour and icons.
// Adapted to the sidebar: a full-width row with a label when the rail is
// expanded, an icon alone (named by aria-label and title) when collapsed.

import { useEffect, useState } from "react";
import { applyTheme, currentTheme, type Theme } from "@/lib/theme";

export function ThemeToggle({ wide }: { wide: boolean }) {
  const [theme, setTheme] = useState<Theme>(() => currentTheme());

  useEffect(() => {
    // Follow the system while no choice is saved.
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setTheme(currentTheme());
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const next: Theme = theme === "dark" ? "light" : "dark";
  const label = `Switch to ${next} mode`;

  return (
    <button
      type="button"
      onClick={() => {
        applyTheme(next);
        setTheme(next);
      }}
      title={label}
      aria-label={label}
      className="flex min-h-9 w-full items-center gap-2.5 px-2 text-left text-sm font-medium text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      {wide && <span className="truncate">{next === "dark" ? "Dark mode" : "Light mode"}</span>}
    </button>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path strokeLinecap="round" d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" />
    </svg>
  );
}
