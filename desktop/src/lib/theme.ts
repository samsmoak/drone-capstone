// PARITY: web/lib/theme.ts — same mechanism and storage key. Adapted only
// where the window forces it: the saved choice is applied from main.tsx, first
// thing, rather than by an inline <head> script, because the window's CSP
// allows no inline script.

/**
 * Light and dark, chosen by the operator and remembered.
 *
 * styles.css already carries both themes: the system setting picks one, and
 * `data-theme="light" | "dark"` on <html> overrides it. No choice saved means
 * follow the system. The webview's localStorage persists across launches;
 * every access is wrapped so a blocked store only loses the memory, never the
 * switch.
 */

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "dronedeck-theme";

/** Put the saved choice on <html>. Called once, before React renders. */
export function bootTheme(): void {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  } catch {
    /* storage blocked — follow the system */
  }
}

/** The theme on screen now: the saved override if any, else the system's. */
export function currentTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Put a theme on screen and remember it. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage blocked — the choice holds until the window closes */
  }
}
