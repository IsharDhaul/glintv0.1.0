// A live evaluation shaped like the API's ScreenResponse, so the sieve, table and near misses
// render the same way whichever produced it. The server's response replaces it once current.

import type { components } from "@/lib/api/types";
import { noteAt } from "@/lib/data/snapshot";
import type { Evaluation, ScreenEngine } from "./engine";
import type { Screen } from "./types";

type S = components["schemas"];

const DEFAULT_COLUMNS = ["ticker", "name", "sector", "market_cap"];

export function liveResponse(engine: ScreenEngine, screen: Screen, ev: Evaluation, asOf: S["AsOf"], opts: { limit?: number } = {}): S["ScreenResponse"] {
  const cols = screen.columns && screen.columns.length > 0 ? screen.columns : DEFAULT_COLUMNS;
  const rows = engine.store.rows;
  const results = engine
    .order(screen, ev)
    .slice(0, opts.limit ?? screen.limit)
    .map((i): S["ResultRow"] => {
      const sc = ev.scores.get(i);
      const values: S["ResultRow"]["values"] = {};
      const notes: S["ResultRow"]["notes"] = {};
      for (const c of cols) {
        if (c === "rank_score") {
          values[c] = sc?.score ?? null;
          if (sc?.note) notes[c] = sc.note;
          continue;
        }
        values[c] = engine.cell(c, i);
        const code = noteAt(engine.store, c, i);
        // Codes only: the messages stay server-side and arrive with the authoritative response.
        if (code) notes[c] = { code, message: "" };
      }
      return {
        cik: rows.cik[i] as string,
        ticker: rows.ticker[i] as string,
        name: rows.name[i] as string,
        sector: rows.sector[i] as S["Sector"],
        rank: ev.positions.get(i) ?? null,
        rank_score: sc?.score ?? null,
        factor_contributions: sc?.contributions ?? {},
        values,
        notes,
      };
    });
  return {
    build_id: engine.store.buildId,
    as_of: asOf,
    universe_count: ev.universe.length,
    funnel: ev.funnel,
    total: ev.passing.length,
    results,
    near_misses: screen.near_misses ? ev.nearMisses : [],
    warnings: [],
  };
}

/**
 * Does the server's answer match the preview? Same funnel, and the server's rows (capped by its
 * `limit`) are the first rows of the preview's (which has every passing company).
 */
export function sameAnswer(preview: S["ScreenResponse"], server: S["ScreenResponse"]): boolean {
  const f = (r: S["ScreenResponse"]) => r.funnel.map((s) => `${s.remaining}/${s.removed}/${s.removed_missing}/${s.binding}`).join(",");
  const t = (rows: S["ResultRow"][]) => rows.map((x) => x.ticker).join(",");
  return f(preview) === f(server) && t(preview.results.slice(0, server.results.length)) === t(server.results);
}
