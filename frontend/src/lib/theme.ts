/**
 * Accent palettes for the whole application.
 *
 * The app was already built entirely on CSS custom properties, so a theme is
 * nothing more than an attribute on <html> — no context, no re-render, no
 * per-component wiring. The swatch colours below are duplicated from
 * globals.css purely so the picker can show what it is offering; the palette
 * that actually renders always comes from the stylesheet.
 */

export const THEMES = [
  { key: "slate", label: "Slate Blue", swatch: "#2f4f7f", note: "The default — quiet and neutral." },
  { key: "indigo", label: "Indigo", swatch: "#4c46b6", note: "Cooler and a touch more modern." },
  { key: "teal", label: "Teal", swatch: "#0f6b6b", note: "Calm; reads well over long sessions." },
  { key: "forest", label: "Forest", swatch: "#2c6b3f", note: "Green, but darker than the 'paid' green." },
  { key: "terracotta", label: "Terracotta", swatch: "#a1462a", note: "Warm and earthy; suits textiles." },
  { key: "graphite", label: "Graphite", swatch: "#3a4048", note: "Near-monochrome. Colour left to status only." },
] as const;

export type ThemeKey = (typeof THEMES)[number]["key"];

export const DEFAULT_THEME: ThemeKey = "slate";
const STORAGE_KEY = "ecolink-theme";

export function isThemeKey(value: unknown): value is ThemeKey {
  return THEMES.some((t) => t.key === value);
}

export function readTheme(): ThemeKey {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isThemeKey(stored) ? stored : DEFAULT_THEME;
  } catch {
    // Private browsing throws on access rather than returning null.
    return DEFAULT_THEME;
  }
}

export function writeTheme(theme: ThemeKey) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* The theme still applies for this session. */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/* --- external store -------------------------------------------------------
   The chosen theme lives in localStorage, which React cannot see. Exposing it
   as a store lets the picker read it with useSyncExternalStore: the server and
   the first client render both produce DEFAULT_THEME, then React swaps in the
   real value without the extra render an effect would cause. Snapshots are
   plain strings, so referential stability is not a concern. */

const CHANGE_EVENT = "ecolink-theme-change";

export const themeStore = {
  subscribe(onChange: () => void) {
    window.addEventListener(CHANGE_EVENT, onChange);
    // Another tab changing the theme fires `storage`, not our event.
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  },
  getSnapshot: readTheme,
  getServerSnapshot: (): ThemeKey => DEFAULT_THEME,
};

/**
 * Runs before first paint, inlined into <head>. Without it the page renders in
 * the default palette and then snaps to the chosen one — the flash is small but
 * it happens on every navigation.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY,
)});var ok=${JSON.stringify(THEMES.map((t) => t.key))};document.documentElement.setAttribute("data-theme",ok.indexOf(t)>-1?t:${JSON.stringify(
  DEFAULT_THEME,
)});}catch(e){}})();`;
