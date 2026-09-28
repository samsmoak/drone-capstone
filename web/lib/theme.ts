/**
 * Light and dark, chosen by the visitor and remembered.
 *
 * The tokens in app/globals.css already carry both themes: the system setting
 * picks one, and `data-theme="light" | "dark"` on <html> overrides it. So the
 * whole mechanism is that one attribute plus a saved choice:
 *
 *   - no choice saved   follow the operating system (no attribute set)
 *   - a choice saved    `data-theme` set from localStorage before first paint
 *
 * localStorage, not a cookie: nothing on the server needs to know, and a page
 * rendered for one visitor is never cached with another visitor's theme.
 * Every access is wrapped — storage can be blocked (private windows, strict
 * settings), and then the toggle still works for the page, just not remembered.
 */

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "dronedeck-theme";

/** Runs in <head> before the body paints. Kept tiny and dependency-free. */
export const THEME_BOOT_SCRIPT =
  `try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});` +
  `if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

/** The theme on screen now: the saved override if any, else the system's. */
export function currentTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Fired on window whenever applyTheme changes the theme, so every toggle follows. */
export const THEME_EVENT = "dronedeck-theme";

/** Put a theme on screen and remember it. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    /* storage blocked — the choice holds for this page only */
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

/**
 * For useSyncExternalStore: call back when the theme on screen may have
 * changed — a toggle anywhere on the page, another tab (storage), or the
 * system setting while no choice is saved.
 */
export function subscribeTheme(onChange: () => void): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onStorage = (e: StorageEvent) => {
    if (e.key !== THEME_STORAGE_KEY) return;
    if (e.newValue === "light" || e.newValue === "dark") document.documentElement.dataset.theme = e.newValue;
    onChange();
  };
  media.addEventListener("change", onChange);
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    media.removeEventListener("change", onChange);
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}
