import { decodeScreen, encodeScreen } from "./codec";
import { emptyScreen } from "./defaults";
import type { Screen } from "./types";

// Screen ↔ `?s=` (SPEC §2.12, §3.3). Pure helpers; useScreenUrlState wires them to history.

/** JSON with object keys sorted, so equal screens compare equal whatever order edits left. */
export function stableJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stableJson).join(",")}]`;
  if (v && typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>)
      .filter(([, x]) => x !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, x]) => `${JSON.stringify(k)}:${stableJson(x)}`).join(",")}}`;
  }
  return JSON.stringify(v);
}

export function sameScreen(a: Screen, b: Screen): boolean {
  return stableJson(a) === stableJson(b);
}

/** The `s` value for a screen; null for the empty screen, so a fresh screener is a clean "/". */
export function screenParam(screen: Screen): string | null {
  return sameScreen(screen, emptyScreen()) ? null : encodeScreen(screen);
}

/** The screen a URL's `s` describes (empty screen when absent or unreadable). */
export function screenFromParam(s: string | null): Screen {
  return decodeScreen(s) ?? emptyScreen();
}

/** The query string with `s` set (or removed), keeping every other parameter as it was. */
export function withScreenParam(search: string, s: string | null): string {
  const params = new URLSearchParams(search);
  if (s === null) params.delete("s");
  else params.set("s", s);
  const q = params.toString();
  return q ? `?${q}` : "";
}

/**
 * The non-screen UI state that rides in the URL: the selected ticker, whether its drawer is open,
 * and the companies pinned for comparison (at most MAX_PINNED).
 */
export type UiParams = { ticker: string | null; drawer: boolean; pinned?: string[] };

export const MAX_PINNED = 3;

/** `t` and `d` from a query string. A drawer can't be open without a ticker. */
export function uiFromSearch(search: string): UiParams {
  const params = new URLSearchParams(search);
  const ticker = params.get("t")?.trim().toUpperCase() || null;
  const pinned = (params.get("c") ?? "")
    .split(",")
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, MAX_PINNED);
  return { ticker, drawer: ticker !== null && params.get("d") === "1", pinned };
}

/** The query string with `t` and `d` set (or removed), keeping every other parameter. */
export function withUiParams(search: string, ui: UiParams): string {
  const params = new URLSearchParams(search);
  if (ui.ticker) params.set("t", ui.ticker);
  else params.delete("t");
  if (ui.ticker && ui.drawer) params.set("d", "1");
  else params.delete("d");
  if (ui.pinned !== undefined) {
    if (ui.pinned.length > 0) params.set("c", ui.pinned.slice(0, MAX_PINNED).join(","));
    else params.delete("c");
  }
  const q = params.toString();
  return q ? `?${q}` : "";
}

/**
 * A shareable absolute URL for a screen on the screener, with the selected ticker and open drawer
 * when given (never transient params like ?mock=).
 */
export function shareUrl(origin: string, screen: Screen, ui: UiParams = { ticker: null, drawer: false }): string {
  const s = screenParam(screen);
  return `${origin}/${withUiParams(s ? `?s=${s}` : "", ui)}`;
}
