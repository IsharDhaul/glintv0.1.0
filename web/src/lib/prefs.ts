// Density is an attribute on <html>, persisted per browser in localStorage. There is one theme
// (light), so no theme preference exists.

export type Density = "compact" | "comfortable";

export const DENSITY_KEY = "glint.density";

/** Runs in <head> before first paint so the stored density never flashes. */
export const PREFS_SCRIPT = `(function(){var d=document.documentElement;try{var n=localStorage.getItem("${DENSITY_KEY}");if(n==="compact"||n==="comfortable")d.dataset.density=n}catch(e){}})();`;

export function applyPref(attr: "density", value: string, key: string): void {
  document.documentElement.dataset[attr] = value;
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage blocked (private mode): the choice lasts for this page only.
  }
}
