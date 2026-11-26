// The mock's companies as a snapshot (what /api/snapshot/* serves in mock mode), and as a column
// store for the shared screen engine (lib/screen/engine.ts).

import type { components } from "@/lib/api/types";
import { decodeSnapshot, encodeSnapshot, type Store } from "@/lib/data/snapshot";
import type { MockData } from "./generate";

type S = components["schemas"];

const NOTE_CODES: S["NoteCode"][] = [
  "MISSING_INPUT",
  "NEGATIVE_DENOMINATOR",
  "NOT_APPLICABLE_SECTOR",
  "FOREIGN_PRICE_BASIS",
  "INSUFFICIENT_HISTORY",
  "STALE_DATA",
  "NO_INTEREST_EXPENSE",
  "SMALL_PEER_GROUP",
  "DERIVED_INPUT",
  "ASSUMED_TAX_RATE",
];

export function mockSnapshot(data: MockData): { meta: S["SnapshotMeta"]; body: ArrayBuffer } {
  const rows = [...data.rows].sort((a, b) => (a.cik < b.cik ? -1 : 1)); // engine: ORDER BY cik
  const metrics = data.metrics.map((m) => m.id).filter((id) => rows.some((r) => id in r.values));
  const bool = new Set(data.metrics.filter((m) => m.unit === "bool").map((m) => m.id));
  const body = encodeSnapshot(
    metrics,
    rows.length,
    (id, i) => {
      const v = rows[i]?.values[id];
      if (v === null || v === undefined) return null;
      return bool.has(id) ? (v ? 1 : 0) : (v as number);
    },
    (id, i) => {
      const code = rows[i]?.notes[id]?.code;
      return code ? NOTE_CODES.indexOf(code) + 1 : 0;
    },
  );
  const prof = (cik: string) => data.profiles[cik];
  const meta: S["SnapshotMeta"] = {
    build_id: data.meta.build_id,
    n: rows.length,
    metrics,
    note_codes: NOTE_CODES,
    rows: {
      cik: rows.map((r) => r.cik),
      ticker: rows.map((r) => r.ticker),
      name: rows.map((r) => r.name),
      sector: rows.map((r) => r.sector),
      exchange: rows.map((r) => prof(r.cik)?.header.exchange ?? null),
      kind: rows.map((r) => prof(r.cik)?.header.kind ?? "synthetic"),
      is_foreign_filer: rows.map((r) => prof(r.cik)?.header.is_foreign_filer ?? false),
      is_stale: rows.map((r) => prof(r.cik)?.is_stale ?? false),
      has_facts: rows.map((r) => prof(r.cik)?.header.has_facts ?? true),
    },
    screen_config: data.config,
    values_bytes: rows.length * metrics.length * 8,
    notes_bytes: rows.length * metrics.length,
  };
  return { meta, body };
}

let cached: { data: MockData; store: Store } | null = null;

/** The mock data as a column store (memoised per data object). */
export function mockStore(data: MockData): Store {
  if (cached?.data !== data) {
    const { meta, body } = mockSnapshot(data);
    cached = { data, store: decodeSnapshot(meta, body) };
  }
  return cached.store;
}
