/**
 * Appearance: system, light or dark.
 *
 * The six accent palettes this file used to hold are gone. A choice was made —
 * graphite and slate blue — and baking it into globals.css means the tokens are
 * the design rather than one option among six. What remains worth choosing is
 * whether to follow the OS, since the dark treatment is the intended one but
 * nobody should be forced into it under an office ceiling light.
 *
 * The value lives in localStorage, which React cannot observe, so it is exposed
 * as an external store instead of being synced into state inside an effect.
 */

export const APPEARANCES = [
  { key: "system", label: "System", hint: "Follow the operating system" },
  { key: "dark", label: "Flight deck", hint: "Graphite and backlit blue" },
  { key: "light", label: "Daylight", hint: "The same panel, lit from outside" },
] as const;

export type Appearance = (typeof APPEARANCES)[number]["key"];

export const DEFAULT_APPEARANCE: Appearance = "system";
const STORAGE_KEY = "ecolink-appearance";
const CHANGE_EVENT = "ecolink-appearance-change";

export function isAppearance(value: unknown): value is Appearance {
  return APPEARANCES.some((a) => a.key === value);
}

export function readAppearance(): Appearance {
  if (typeof window === "undefined") return DEFAULT_APPEARANCE;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isAppearance(stored) ? stored : DEFAULT_APPEARANCE;
  } catch {
    // Private browsing throws on access rather than returning null.
    return DEFAULT_APPEARANCE;
  }
}

export function writeAppearance(value: Appearance) {
  // "system" removes the attribute entirely, handing the decision back to the
  // prefers-color-scheme media query.
  if (value === "system") document.documentElement.removeAttribute("data-appearance");
  else document.documentElement.setAttribute("data-appearance", value);

  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* The choice still applies for this session. */
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export const appearanceStore = {
  subscribe(onChange: () => void) {
    window.addEventListener(CHANGE_EVENT, onChange);
    // Another tab changing it fires `storage`, not our event.
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  },
  getSnapshot: readAppearance,
  getServerSnapshot: (): Appearance => DEFAULT_APPEARANCE,
};

/**
 * Runs before first paint, inlined into <head>. Without it the page renders in
 * the OS appearance and then snaps to the stored one — a brief flash of the
 * wrong panel on every hard load.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var v=localStorage.getItem(${JSON.stringify(
  STORAGE_KEY,
)});if(v==="dark"||v==="light")document.documentElement.setAttribute("data-appearance",v);}catch(e){}})();`;
