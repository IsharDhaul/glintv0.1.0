# WT-06 · metrics ★

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 2 | L | WT-01, WT-02, WT-03 | `wt06-metrics` | `worktree-wt06-metrics` | — |

**Goal.** Compute every P0 metric (and as many P1 as time allows) for every company, with a reason code for every null. Also flags, data quality and the snapshot archive. This is where the numbers you'll quote in pitches get made.

**Owns.** `engine/glint/metrics/`, `engine/glint/flags/`, `engine/glint/quality/`, `config/thresholds.yaml`, the `formula`/`status`/`applicability` fields of `config/metrics.yaml`, `engine/tests/metrics/`, `docs/decisions/WT-06.md`.

**Must not touch.** Financials logic (ask WT-03's owner, which is you on `main`, via a small PR), contracts, screen, API.

**Steps**

1. **Inputs frame.** One polars frame per build joining:
   - `companies`
   - Latest TTM, MRQ and averages
   - TTM 1 year ago (for growth and changes)
   - FY series (for CAGR and Piotroski)
   - `price_stats` for the **primary ticker**
   - Shares with `shares_as_of`

   Finalize `primary_ticker` as the class with the highest `avg_dollar_volume_3m`.
2. **Market cap and EV.**
   - Market cap = unadjusted close × shares. Check for a split between `shares_as_of` and the price date (WT-02 helper): adjust with the ratio noted, or null with a reason.
   - Apply the multi-class rules from `share_classes.yaml`.
   - Foreign filers get `FOREIGN_PRICE_BASIS` unless they're eligible (§4.3 rule 13).
3. **Metric functions.** One pure function per metric id, registered by id. Each returns `(values, note_codes)`. Implement **all P0 first**, category by category, with unit tests on tiny hand-built frames (including the negative-denominator, missing-input and n/m paths).
4. **Applicability.** Apply the §4.5 matrix from `metrics.yaml` after computing, and override with `NOT_APPLICABLE_SECTOR`.
5. **Composite scores.**
   - `piotroski_f`, with all 9 components stored in `metric_history` or as a JSON evidence column for drill-down.
   - `altman_z` and `greenblatt_roc`.
6. **History.** `metric_history` for the drawer sparklines and change metrics: revenue, operating_margin, fcf, share count, roic and gross_margin (FY last 10 + TTM last 12).
7. **Flags.** A rule engine reading `thresholds.yaml`. It renders the question text with evidence values (formatted with units) and stores them in `flags`.
8. **Quality.** `data_coverage`, `days_since_filing` and `flag_count`.
9. **Write and archive.**
   - Write `metrics_snapshot` (wide), `metric_notes`, `metric_history`, `flags` and quality into the build.
   - Archive the snapshot to `GLINT_RAW_DIR/snapshots/date=<as_of>/` as Parquet. **This starts your point-in-time history.**
10. **Registry sync.** Every `live` id has a function and vice versa, and `status` flips to `live` as each metric lands. A test enforces it.
11. **Audit** (`glint audit`): §4.6 rules plus a per-metric distribution (p1/p5/p50/p95/p99, null % by reason) for the whole universe. It prints the top outliers for each rule with the company and the inputs behind them.
12. **CLI.** `glint metrics AAPL [--category valuation] [--explain roic]`. `--explain` prints the formula, every input with its value, period, source tag and accession, and the result.

**Acceptance criteria**

- [ ] Every P0 metric is `live`. The P1s not done stay `planned`, and their list is recorded.
- [ ] **Every null has exactly one reason code.** A test scans the whole snapshot.
- [ ] Behaviour checks, as table-driven tests on fixtures:
  - JPM: EV metrics, gross margin, current ratio and Altman are `NOT_APPLICABLE_SECTOR`.
  - SBUX: `pb` and `debt_to_equity` are `NEGATIVE_DENOMINATOR`.
  - RIVN: `pe_ttm` is `NEGATIVE_DENOMINATOR` and `earnings_yield` < 0.
  - TSM: price metrics are `FOREIGN_PRICE_BASIS`, and margins are present.
- [ ] **Hand-check:** for 5 companies (AAPL, KO, NVDA, KHC, XOM), you recompute 6 metrics each from the 10-K in a spreadsheet: gross_margin, operating_margin, roic, fcf_margin, net_debt_to_ebitda, revenue_growth_yoy. All are within 0.5% and entered as golden rows.
- [ ] `glint audit` runs on the full universe. Every outlier class has been looked at, and is either fixed upstream or explained in the decisions file.
- [ ] Null rate per P0 metric for domestic non-financials is recorded. Core metrics are ≥ 90% non-null, or the gap is explained.
- [ ] The same raw inputs produce an identical snapshot (determinism test).

**Demo commands:** `glint metrics AAPL --explain roic` · `glint metrics JPM` · `glint audit --top 10`.

**Decisions to record:** the tax-rate rule as implemented; the invested-capital definition; primary-ticker selection; null rates; every audit finding and what you did about it.

**Gotchas**

- Don't mix bases: TTM flows with MRQ instants, and averages use the 1-year-ago instant.
- Tiny denominators create absurd ratios. **Don't clip for display**, but the audit has to surface them.
- Never fall back to a provider's market cap or ratio. Compute it or null it.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-06 (metrics).
Your brief: docs/worktrees/WT-06-metrics.md. Spec context: docs/SPEC.md §2.4 (every definition is binding), §2.10, §4.3 rules 11–13, §4.5, §4.6.
Build a real database from shared raw data first (I'll tell you if WT-07's `glint refresh --no-download` exists yet; otherwise call the stages directly).
For every metric: write the test with hand-computed numbers before the implementation. Show me `glint metrics <T> --explain <metric>` for anything that looks off before changing a rule.
```
