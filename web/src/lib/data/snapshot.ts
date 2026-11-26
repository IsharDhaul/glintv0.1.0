// The build's metric values as columns (/api/snapshot/meta + /api/snapshot/values), for the live
// screen preview (docs/interaction-architecture.md). The browser compares these numbers with the
// user's thresholds; it never computes a metric, and the server stays authoritative.

import type { components } from "@/lib/api/types";

type S = components["schemas"];
export type SnapshotMeta = S["SnapshotMeta"];
export type NoteCode = S["NoteCode"];

export type Store = {
  buildId: string | null;
  n: number;
  metrics: string[];
  /** Row index by cik. */
  index: Map<string, number>;
  rows: SnapshotMeta["rows"];
  config: SnapshotMeta["screen_config"];
  noteCodes: NoteCode[];
  /** NaN = null. Booleans are 1/0. */
  col(metric: string): Float64Array | undefined;
  /** 0 = no note, k = noteCodes[k - 1]. */
  code(metric: string): Uint8Array | undefined;
};

/** Read the values body against its meta. Throws if the sizes don't match (a different build). */
export function decodeSnapshot(meta: SnapshotMeta, body: ArrayBuffer): Store {
  const m = meta.metrics.length;
  const n = meta.n;
  if (body.byteLength !== meta.values_bytes + meta.notes_bytes || meta.values_bytes !== n * m * 8) {
    throw new Error(`Snapshot body is ${body.byteLength} bytes; meta expects ${meta.values_bytes + meta.notes_bytes}.`);
  }
  // Float64Array needs an 8-byte-aligned offset: the values come first, at offset 0.
  const values = new Float64Array(body, 0, n * m);
  const notes = new Uint8Array(body, meta.values_bytes, n * m);
  const pos = new Map(meta.metrics.map((id, j) => [id, j]));
  const colCache = new Map<string, Float64Array>();
  const codeCache = new Map<string, Uint8Array>();
  return {
    buildId: meta.build_id,
    n,
    metrics: meta.metrics,
    index: new Map(meta.rows.cik.map((c, i) => [c, i])),
    rows: meta.rows,
    config: meta.screen_config,
    noteCodes: meta.note_codes,
    col(metric) {
      const j = pos.get(metric);
      if (j === undefined) return undefined;
      let c = colCache.get(metric);
      if (!c) colCache.set(metric, (c = values.subarray(j * n, (j + 1) * n)));
      return c;
    },
    code(metric) {
      const j = pos.get(metric);
      if (j === undefined) return undefined;
      let c = codeCache.get(metric);
      if (!c) codeCache.set(metric, (c = notes.subarray(j * n, (j + 1) * n)));
      return c;
    },
  };
}

/** The note code for one cell, or null. */
export function noteAt(store: Store, metric: string, i: number): NoteCode | null {
  const k = store.code(metric)?.[i] ?? 0;
  return k === 0 ? null : (store.noteCodes[k - 1] ?? null);
}

/** The value for one cell: a number, a boolean (bool metrics), or null. */
export function valueAt(store: Store, metric: string, i: number, bool = false): number | boolean | null {
  const v = store.col(metric)?.[i];
  if (v === undefined || Number.isNaN(v)) return null;
  return bool ? v !== 0 : v;
}

/** Encode a store's columns as the API would (used by the mock server and tests). */
export function encodeSnapshot(metrics: string[], n: number, value: (metric: string, i: number) => number | null, code: (metric: string, i: number) => number): ArrayBuffer {
  const m = metrics.length;
  const buf = new ArrayBuffer(n * m * 9);
  const values = new Float64Array(buf, 0, n * m);
  const notes = new Uint8Array(buf, n * m * 8, n * m);
  metrics.forEach((id, j) => {
    for (let i = 0; i < n; i++) {
      const v = value(id, i);
      values[j * n + i] = v === null ? Number.NaN : v;
      notes[j * n + i] = code(id, i);
    }
  });
  return buf;
}
