# WT-04 · screen-engine

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 1 | M | WT-00 | `wt04-screen-engine` | `worktree-wt04-screen-engine` | — |

**Goal.** Compile any valid Screen JSON into fast, safe DuckDB SQL over `metrics_snapshot`. Return results, the sieve, near misses and rank scores with factor contributions. It's developed entirely against the synthetic build.

**Owns.** `engine/glint/screen/`, `engine/tests/screen/`, 3 starter presets in `config/presets/` (`magic-formula.json`, `quality-compounders.json`, `dilution-watch.json`), `docs/decisions/WT-04.md`.

**Must not touch.** Contracts (the DSL is fixed; use the protocol), the API, the web.

**Steps**

1. **Semantic validation** on top of pydantic: ids exist and are `live`; the comparator suits the unit; `between` order; weights; depth.
   - **Synthetic builds treat every registry id as live.** Make this a flag on the registry loader, not a hack.
2. **Universe stage.** SQL `WHERE` clauses from the `universe` block, with every value bound as a parameter. Column names come only from the registry allow-list.
3. **Relative stats.** Compute `percent_rank()` and the sector median with window functions **over the universe-filtered set**. If a sector has fewer than 5 companies, the result is null with `SMALL_PEER_GROUP`.
4. **Filter compiler.** Handles every comparator in §2.5, AND/OR nesting, `missing: fail|pass` and the float tolerance from `thresholds.yaml`.
5. **Sieve.** Sequential counts per top-level AND child, with `removed` and `removed_missing`. An OR group is one step. Mark the binding step.
6. **Near misses.** Companies that pass the universe and fail exactly one top-level filter, closest first (§2.7), up to 25, with the failed filter, value and threshold.
7. **Ranking.**
   - `percentile_composite`: direction-aware, weights re-normalized over present factors, `min_factor_coverage`.
   - `rank_sum`.
   - Contributions per factor.
   - Deterministic tie-break by ticker.
8. **Results.** Assemble the requested columns plus per-cell note codes, sort, limit and total.
9. **Presets.** A loader that validates `config/presets/*.json` at startup, plus the 3 starters (thresholds are provisional; WT-10 tunes them).
10. **CLI.** `glint screen <file.json|preset-id> [--synthetic] [--explain]` prints the sieve, the top results and the near misses. `--explain` prints the SQL with parameters.
11. **Performance check.** 10 filters with near misses on 6,000 synthetic rows: p95 < 100 ms in-process (pytest-benchmark or a timing loop).

**Acceptance criteria**

- [ ] Property tests over random valid screens (seeded): every result satisfies every filter, sieve counts never increase, and every near miss fails exactly one top-level filter.
- [ ] An injection test: a metric id like `roic; DROP TABLE` is rejected at validation, and no SQL string concatenation of user values exists (grep test).
- [ ] Percentiles are computed after universe filters, proven by a test where changing the universe changes the percentiles.
- [ ] `missing: pass` vs `fail` behaves correctly, and `removed_missing` is accurate.
- [ ] Rank output is deterministic across 3 runs.
- [ ] p95 < 100 ms is recorded.
- [ ] The 3 starter presets validate and run on synthetic data.

**Demo commands:** `glint screen magic-formula --synthetic` · `glint screen quality-compounders --synthetic --explain`.

**Decisions to record:** how pp and vs-median comparisons were implemented; the near-miss distance for percentile filters; the performance numbers.

**Gotchas**

- Percent values are fractions everywhere. A threshold of `15` for ROIC is a bug the validator should warn on: `|value| > 2` for a `frac` metric triggers a warning.
- `percent_rank()` on nulls: exclude them from the window, then join back.
- Don't compute any metrics here. Read the snapshot only.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-04 (screen-engine).
Your brief: docs/worktrees/WT-04-screen-engine.md. Spec context: docs/SPEC.md §2.5–2.8, §5.4.
Build and test only against the synthetic build (`glint fixtures synthetic`). All user values are bound parameters; identifiers come only from the registry allow-list.
```
