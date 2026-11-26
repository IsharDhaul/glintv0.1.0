import { DEFAULT_COLUMNS } from "./defaults";
import type { Screen } from "./types";

// Table chrome: the flag-count and coverage badges are registry metrics that results requests
// carry whatever the user picked, but only when the build serves them: the API rejects columns
// that aren't live (review fix: on a real build they're `planned` until WT-06).
export const BADGE_COLUMNS = ["flag_count", "data_coverage"] as const;

/** Columns the user chose (the screen's own), ticker first, badges excluded. */
export function userColumns(screen: Screen): string[] {
  const cols = screen.columns && screen.columns.length > 0 ? screen.columns : DEFAULT_COLUMNS;
  const rest = cols.filter((c) => c !== "ticker" && !(BADGE_COLUMNS as readonly string[]).includes(c));
  return ["ticker", ...rest];
}

/**
 * The screen as requested: user columns plus whichever badge columns are live. `live` is the
 * set of metric ids `/api/metrics` returned (it lists live metrics only).
 */
export function withBadgeColumns(screen: Screen, live: { has(id: string): boolean }): Screen {
  return { ...screen, columns: [...withScore(screen, userColumns(screen)), ...BADGE_COLUMNS.filter((c) => live.has(c))] };
}

/** On a ranked screen the Score column is always shown, right after the name (or the ticker). */
function withScore(screen: Screen, cols: string[]): string[] {
  if (!screen.rank || screen.rank.factors.length === 0) return cols;
  const rest = cols.filter((c) => c !== "rank_score");
  const at = rest.indexOf("name") >= 0 ? rest.indexOf("name") + 1 : 1;
  return [...rest.slice(0, at), "rank_score", ...rest.slice(at)];
}

/** Badge columns a response actually carries (absent ones aren't drawn, rather than shown as "—"). */
export function responseBadges(res: { results: { values: Record<string, unknown> }[] }): string[] {
  const first = res.results[0];
  return first ? BADGE_COLUMNS.filter((c) => c in first.values) : [];
}

/**
 * The columns a response actually carries (its first row's `values`, which follow the request
 * order), so placeholder rows from a previous request never sit under another request's headers
 * as reason-less "—". Falls back to the screen when there are no rows.
 */
export function responseColumns(res: { results: { values: Record<string, unknown> }[] }, screen: Screen): string[] {
  const first = res.results[0];
  if (!first) return userColumns(screen);
  return userColumns({ ...screen, columns: Object.keys(first.values) });
}

/** Show a metric's column (added after the last one) unless it's already there or isn't a metric column. */
export function withMetricColumn(screen: Screen, metric: string, isMetric: boolean): Screen {
  const cols = userColumns(screen);
  if (!isMetric || cols.includes(metric)) return screen;
  return { ...screen, columns: [...cols, metric] };
}

export function setColumns(screen: Screen, columns: string[]): Screen {
  return { ...screen, columns: ["ticker", ...columns.filter((c) => c !== "ticker")] };
}

export type SortDir = "asc" | "desc";

/** The sort the API applies: the screen's, else rank_score desc when ranked, else ticker asc. */
export function effectiveSort(screen: Screen): { by: string; dir: SortDir } {
  if (screen.sort) return screen.sort;
  return screen.rank ? { by: "rank_score", dir: "desc" } : { by: "ticker", dir: "asc" };
}

/**
 * Next sort when a header is clicked: a new column starts descending for numbers (biggest
 * first) and ascending for text; clicking again flips; a third click returns to the default.
 */
export function nextSort(screen: Screen, column: string, numeric: boolean): Screen["sort"] {
  const cur = effectiveSort(screen);
  const first: SortDir = numeric ? "desc" : "asc";
  if (cur.by !== column || !screen.sort) return { by: column, dir: first };
  if (cur.dir === first) return { by: column, dir: first === "desc" ? "asc" : "desc" };
  return null;
}
