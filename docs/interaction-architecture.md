# Interaction architecture

Phase 3 of `docs/glint-ui-upgrade.md`. Read alongside `docs/ui-spec.md` §8, which lists the questions this document answers.

## Decision in one paragraph

The browser loads the build's metrics once, as a compact **columnar payload** (Float64 per metric plus a reason code per cell), cached forever by `build_id`. It evaluates the screen **client-side** for everything that has to feel live: sieve counts, histogram colouring, the results table, near misses. The rules are the engine's, the same ones `web/src/mocks/evaluate.ts` already mirrors. When an edit settles, the API's `/api/screen` runs as today, and its answer is **authoritative**. A CI test fails if the two ever disagree on the synthetic build, and the UI shows the server's result whenever it differs.

## Diagram

```
                         once per build (immutable, cached by build_id)
 ┌──────────────┐   GET /api/snapshot?build=…   ┌──────────────────────────────┐
 │  DuckDB      │ ─────────────────────────────▶│ Columnar store (browser)     │
 │  build       │   Float64 × 70 metrics        │ cols[metric]: Float64Array   │
 │  (read-only) │   Uint8 reason code per cell  │ notes[metric]: Uint8Array    │
 └──────┬───────┘   ticker/name/sector/exchange │ cats: sector, exchange, kind │
        │                                       └──────────────┬───────────────┘
        │                                                      │
        │  POST /api/screen  (on settle, 400 ms)               │  every input event
        │                                                      ▼
        │                            ┌───────────────────────────────────────────────┐
        │                            │ ScreenState  (one object, serialised to URL)  │
        │                            │ screen: filters, universe, rank, columns, sort│
        │                            │ ui: selected ticker, drawer open, pinned[≤3]  │
        │                            └──────────────┬────────────────────────────────┘
        │                                           │ derive (pure, ~3 ms at 4× throttle)
        │                                           ▼
        │                     universe mask → stats (percentiles, medians; cached per universe)
        │                     → leaf masks (one per filter; only the edited one recomputes)
        │                     → funnel (kept / failed / no data per stage)
        │                     → passing rows (sorted) → virtual table window (~30 rows)
        │                     → near misses (fail exactly one) → histogram bins (expanded filter)
        ▼                                           │
 ┌─────────────────────────┐   compare on settle    │
 │ Server ScreenResponse   │◀───────────────────────┘
 │ (authoritative: funnel, │   equal → nothing changes on screen
 │  results, near misses)  │   different → server result replaces the preview, and the
 └─────────────────────────┘   difference is logged as a console warning
```

## State

- **One object, `ScreenState = { screen: Screen; ui: { ticker: string | null; drawer: boolean; pinned: string[] } }`.** Everything else is derived: funnel, rows, near misses, histograms, the screen check.
- **URL:**
  - `?s=` keeps the lz-string `Screen`, which already powers Share and preset links.
  - `?t=ADBE&d=1&c=ADBE,MSFT` hold the selected ticker, the drawer state and the pins.
  - Screen edits **push** one history entry once settled; that's the existing `useScreenUrlState` behaviour, so Back undoes a filter change.
  - Selection, drawer and pin changes **replace** the entry, so flicking through 40 names with j/k doesn't create 40 Back steps.
- **Library: hand-rolled. The existing `lib/screen/useScreenUrlState.ts` is extended with a `ui` part.**
  - **For:** it's already tested by e2e (`url-state.spec.ts`: Back/Forward, broken links, one entry per settled edit); it uses lz-string encoding the API decodes too; and its history semantics are specific.
  - **Against nuqs:** a new dependency, a re-check against Next 16, and re-implementing the lz-string codec as a nuqs parser anyway.
  - **Cost of hand-rolling:** about 60 more lines and one more e2e spec.

## Computation: measured, not guessed

### Option B, server per edit: measured

`run_screen` on the real build (`20261122T190252Z`, 7,992 rows), 15 runs per preset, warm, in-process (no HTTP):

| Preset | Median | p90 |
|---|---|---|
| cash-rich-smallcaps | 36.8 ms | 39.4 ms |
| accruals-risk | 46.0 ms | 51.5 ms |
| quality-compounders | 79.4 ms | 127.9 ms |
| dilution-watch | 84.7 ms | 107.8 ms |
| net-nets | 233.2 ms | 566.0 ms |

The other seven presets fall between these: medians 49–77 ms, p90s 73–309 ms. That's compute alone. HTTP, JSON and a debounce come on top, so **the server path can't meet 50 ms**, even before network.

### Option A, client columnar: measured

Headless Chromium, the real build's 7,992 × 70 numeric columns as `Float64Array`s, 5 filters. One slider move recomputes the edited leaf mask, the funnel (kept / failed / no data per stage), the passing rows sorted by a rank column, the near misses, and the dragged filter's histogram. 500 timed iterations after warm-up:

| CPU | Median | p95 | Max | Universe change (re-rank 5 percentile columns) |
|---|---|---|---|---|
| Unthrottled (dev laptop) | 1.0 ms | 1.3 ms | 3.0 ms | 13 ms |
| 4× throttle (mid-range laptop proxy) | 3.1 ms | 4.9 ms | 8.0 ms | 43 ms |
| 6× throttle (pessimistic) | 4.7 ms | 6.9 ms | 14.7 ms | 66 ms |

- Compute uses under 10% of the 50 ms budget at 4×. The rest goes to React and rendering a virtualised window of about 30 rows plus the sieve.
- A universe change (43 ms at 4×) only happens when the user edits universe rules, not while dragging.
- **No Web Worker for now.** The main thread has the headroom, and a worker adds copying (or SharedArrayBuffer and COOP/COEP headers) for no measured gain. Revisit if the render half of the budget turns out to be tight.
- **Phase 4 adds a `perf`-marked Playwright test:** drag a handle 50 times at 4× throttle on the synthetic 6,000-row build, and fail if p95 from input event to painted sieve count exceeds 50 ms.

### Payload: measured

| Encoding | Raw | gzip |
|---|---|---|
| Float64 × 70 × 7,992 | 4.48 MB | 1.84 MB |
| Float32 | 2.24 MB | 1.01 MB |

- **Float64.** Float32's worst relative error on this data is 6×10⁻⁸, enough to flip a value sitting on a threshold relative to the engine (`float_tolerance` is 10⁻⁹). Parity with the engine is worth 0.8 MB once per build.
- It's served with `Cache-Control: public, max-age=31536000, immutable`, keyed by `build_id`, so a returning visitor downloads it once per daily build.
- Reason codes are one `Uint8` per cell (~560 KB raw, mostly zeros, so it compresses to little). Note *messages* stay server-side and are fetched with the company.

### Why A doesn't compromise principle 1

The client never computes a metric. It only compares the build's own numbers with the user's thresholds, exactly as the engine's SQL does, and the server re-runs every settled screen. Two guards:
1. **CI parity test.** A Vitest test runs the columnar evaluator and the TypeScript port against the same screens (every preset plus the invariant test screen). An engine-side test exports the synthetic build's `run_screen` output as fixtures. Funnel, result tickers and near misses must match exactly. This extends the Phase 0 invariant suites.
2. **Runtime reconciliation.** If a settled server result differs from the preview, the server's is shown, and a console warning names the screen.

## Histogram binning

- **Client-side, per current universe:**
  - 30 fixed bins over p1–p99 of the metric's values in the universe;
  - explicit `underflow` (< p1) and `overflow` (> p99) counts;
  - `missing` and `notMeaningful` counts from the reason codes.
- They're computed lazily when a filter row expands and cached per (metric, universe). The cost is one sort per metric, about 3 ms at 4× throttle, measured within the percentile rebuild above.
- **No build-time precompute:** bins depend on universe rules, which the user changes.
- `/api/distribution` stays for the API's own clients. The UI stops calling it once the snapshot lands, which also closes the spec's open question about underflow and overflow counts without a contract change to that endpoint.

## Data contract (TypeScript)

```ts
// web/src/lib/data/cell.ts
export type Missing = { kind: "missing"; reason: NoteCode };          // "—"
export type NotMeaningful = { kind: "not_meaningful"; reason: NoteCode }; // "n/m"
export type Value = { kind: "number"; value: number; info?: NoteCode }; // DERIVED_INPUT etc.
export type Cell = Value | Missing | NotMeaningful;

export type Percentile = { p: number; scope: "universe" | Sector; better: Better }; // describePercentile()
export type Flag = { id: FlagId; severity: "caution" | "info"; question: string; evidence: Record<string, unknown> };
```

- `cellAt(store, metric, row): Cell` is the only way components read a value. `NOTE_DISPLAY[code].shown` decides `missing` vs `not_meaningful`, so a raw `number | null` can't reach a component.
- `Flag.severity` comes from `config/thresholds.yaml` through the API. That's a **contract change** (`FlagOut.severity`) and needs its own CONTRACT PR, as `#48` did.
- `/api/snapshot` is also a **new endpoint**, so it's also a CONTRACT change. It returns a small JSON header (`build_id`, `n`, `metrics[]`, `codes[]`, categorical dictionaries, byte offsets) followed by the binary body. It reads from `metrics_snapshot` and `metric_notes` as they are, with no new computation.

## Virtualised table

- `ResultsTable` already uses TanStack Virtual. With the columnar store, the table renders straight from the passing-row index array: a window of about 30 rows, with cells read through `cellAt`.
- The 100-row `limit` stops applying to the UI; the server request keeps `limit` for export and authority.
- Export asks the server for the full set; the contract maximum is 1,000 rows, so an export above that is a separate decision.

## What I'd revisit as the data grows

| Trigger | Change |
|---|---|
| Payload above ~5 MB gzip (for example 10k rows × 150 metrics) | Lazy columns: load only the metrics the screen and visible columns use, plus a manifest. Or Arrow IPC with dictionary encoding. |
| Render half of the budget gets tight (perf test p95 > 35 ms) | Move evaluation to a Web Worker with transferable buffers. Keep the main thread for React only. |
| Universe changes feel slow (> 100 ms at 4×) | Cache sorted index arrays per (metric, universe hash); incremental re-rank. |
| Point-in-time history (WT-14) | One snapshot per as-of date, keyed by `build_id` + date; the URL carries the date. |
| Users on slow connections | Show the server-only path (today's behaviour) until the snapshot arrives; the UI never blocks on it. |

## Open decisions for the user

These go to the user at the end of Phase 3:
1. **Live client-side preview of filter results, with the server authoritative.** This is the only way to hit 50 ms, but it means the browser evaluates filters. The brief asks me to report anything that affects filter results before doing it.
2. **Two contract changes:** the new `/api/snapshot` endpoint and `FlagOut.severity`. Each one is a CONTRACT PR.
