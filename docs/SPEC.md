# Glint: Spec (Parts 1–7)

> Split from the original plan in WT-00. Part 8 lives in `docs/worktrees/README.md`, Part 9 briefs in `docs/worktrees/`, Appendix A is `CLAUDE.md`; Appendices B–F follow Part 7 here.

# Part 1: What Glint is

## 1.1 Pitch

Glint is a fundamentals-first stock screener for US-listed companies.

1. You define a universe.
2. You stack filters.
3. Glint shows how many companies survive each filter: the **sieve**.
4. It ranks the survivors: the **glints**.
5. It lists the companies that missed by one filter: the **near misses**.

Every number has a visible definition and links back to the SEC filing it came from.

## 1.2 Why build it

Existing free screeners (Finviz, Yahoo, TradingView, broker tools) are fast, but they share four problems:

| Problem | What it costs you | What Glint does instead |
|---|---|---|
| **Opaque numbers.** Ratios come from a data vendor with no formula shown. | You can't tell whether "P/E 14" is TTM, forward, GAAP or adjusted. You can't defend it in a pitch. | Glint computes every ratio itself from SEC filings. The formula, inputs, period and filing are one click away. |
| **No "why".** You get a list, not a reason. | You can't see which filter did the real cutting. | The sieve shows the count after each filter, so you can see the binding constraint. |
| **Hard cut-offs hide good ideas.** | A great company with ROIC of 14.9% vanishes from a "≥ 15%" screen. | The near-misses panel lists companies that failed exactly one filter, and by how much. |
| **Garbage for some sectors.** | EV/EBITDA and gross margin for a bank are meaningless, but they show up anyway. | An applicability matrix marks those cells **n/m** and gives the reason. |

**Why it matters for you:** idea generation for Nexus pitches, sector sweeps and thesis checks ("which semis have expanding margins and net cash?"). It also teaches you financial statement analysis, because every metric definition is visible.

## 1.3 Users and jobs to be done

| User | Job | What success looks like |
|---|---|---|
| You (primary) | "Give me 20 names worth an hour of research each." | A screen run takes under 2 minutes. The shortlist exports to CSV. |
| You, learning | "What does ROIC actually mean, and how is it built from the 10-K?" | The metric dictionary shows the formula, XBRL inputs and a worked example for a real company. |
| Nexus analysts (later) | "Show me the cheapest quality names in Industrials this week." | A shared preset plus a shareable link. |
| You, checking a thesis | "Is this company unusual compared with its sector?" | Sector-percentile filters plus the company drawer. |

## 1.4 What Glint is *not*

- **Not a buy/sell tool.** It raises flags as questions, never verdicts. The footer on every page reads: *"Educational tool. Not investment advice."*
- **Not real-time.** Data is end-of-day. Fundamentals arrive as filings get filed.
- **Not global.** The universe is US-listed SEC filers. Foreign companies filing 20-F/40-F are included, with the limits listed in §4.3.
- **Not a backtester (yet).** Doing it honestly needs point-in-time data and delisted companies (§2.15). Glint starts archiving snapshots on day one so that's possible later.
- **Not Taproot.** Taproot explains one company in depth. Glint finds candidates across thousands. They are separate repos and products. Glint copies Taproot's *conventions*, not its code.

## 1.5 Principles (non-negotiable)

These go into `CLAUDE.md` word for word. Every worktree must respect them.

1. **If a number matters, it comes from the source document.** SEC XBRL filings are tier 1. Market prices are a labelled tier 2. AI never supplies numbers.
2. **State your definition.** Every metric carries its formula, inputs (XBRL tags), period basis (TTM/FY/MRQ) and unit. The UI shows them.
3. **Never fabricate.** A missing value is `null` with a **reason code**: "—" in the UI means *missing*, "n/m" means *not meaningful*. No estimates, no fills, no silent zeros.
4. **Compute it yourself.** Glint never imports vendor-computed ratios.
5. **Questions, not verdicts.** Flags are phrased as questions with the evidence attached.
6. **Universe honesty.** Glint always shows what's excluded and why. It never implies the screen covers companies it doesn't.
7. **Comparability before cleverness.** If two companies' numbers aren't comparable (sector, currency, accounting standard), Glint says so instead of ranking them side by side.
8. **Thresholds live in config, never in code.** That covers `config/thresholds.yaml`, `config/metrics.yaml` and `config/presets/`.
9. **Never lose user data.** Pipeline rebuilds can't touch saved screens or watchlists, which live in a separate database file.

## 1.6 Glint and Taproot

- **Separate repos:** `~/Claude/Glint` and `~/Claude/Taproot`. No shared code and no shared database.
- **Shared conventions:** the `preferences.md` you made from Taproot is the baseline: docs at the root, the decisions log, a CLI per feature, fixture-based tests, the SEC gateway pattern and the data principles.
- **Optional link later (v2, P2):** an "Open in Taproot" button that deep-links a ticker, configured by `TAPROOT_URL` in `.env`. Glint must work perfectly without it.

## 1.7 Success criteria for the MVP (v0.1)

The MVP counts as done only when **all** of these are true:

- [ ] One command (`glint refresh`) rebuilds everything from the SEC bulk files and prices. If it fails, the previous build stays live.
- [ ] The universe is built, and real counts by exchange, sector and kind are recorded in `docs/decisions/`.
- [ ] Every P0 metric (§2.4) is live and shows its definition.
- [ ] Core-metric coverage is **≥ 90%** for non-financial US-GAAP filers that filed a 10-K in the last 15 months. This is a target to measure; the real figure gets recorded.
- [ ] `POST /api/screen` p95 is **under 300 ms** on the full universe with 10 filters.
- [ ] **30 golden values** have been hand-checked against filings and pass in tests.
- [ ] 12 presets are working, each with its definition and source.
- [ ] Every null in the snapshot has a reason code (enforced by a test).
- [ ] You've used it for one real Nexus idea-generation session and logged what was missing.

---

# Part 2: Product spec

## 2.1 The core loop

```
Universe ─▶ Filters ─▶ Sieve (counts per step) ─▶ Rank ─▶ Results ─▶ Inspect (drawer) ─▶ Export / Save
   ▲                                                              │
   └──────────────── tweak thresholds using near misses ◀──────────┘
```

## 2.2 Features by phase

Priority: **P0** = MVP must-have · **P1** = v1 · **P2** = v2 · **R** = research or later.

| # | Feature | Priority | Worktree |
|---|---|---|---|
| F1 | Universe builder: exchange, sector, kind exclusions, market-cap band, liquidity floor, filing freshness | P0 | 01, 04, 05 |
| F2 | Metric library, P0 set (~50 metrics, including everything the presets use) with definitions | P0 | 06 |
| F3 | Filter builder: comparators, AND/OR groups, missing-value handling | P0 | 04, 05 |
| F4 | Relative filters: percentile within universe or sector, vs sector median | P0 | 04 |
| F5 | Sieve (funnel counts per filter) | P0 | 04, 05 |
| F6 | Near misses (failed exactly one filter) | P0 | 04, 05 |
| F7 | Ranking: weighted percentile composite plus rank-sum (Greenblatt style), with factor contributions | P0 | 04 |
| F8 | Results table: virtualized, sortable, column picker, null-reason tooltips | P0 | 05 |
| F9 | Company drawer: key metrics, sparklines, flags, source filing links | P0 | 05, 08 |
| F10 | Distribution histogram under each filter's threshold input | P0 | 05, 08 |
| F11 | 12 presets with definitions and citations | P0 | 10 |
| F12 | Metric dictionary page (generated from the registry) | P0 | 05, 10 |
| F13 | CSV export and shareable URL state | P0 | 05, 08 |
| F14 | Data freshness ("as of") everywhere, plus a staleness flag | P0 | 06, 05 |
| F15 | One-command refresh with build-then-swap | P0 | 07 |
| F16 | Flags engine (questions, not verdicts) | P0 | 06 |
| F17 | Snapshot archive from day one (future point-in-time data) | P0 | 06, 07 |
| F18 | P1 metrics (the rest of §2.4) | P1 | 06 |
| F19 | Saved screens, watchlists, "new entrants and leavers since last run" | P1 | 12 |
| F20 | FX conversion plus ADR ratios so foreign filers get price-based metrics | P1 | 03, 06 |
| F21 | Restatement detection flag | P1 | 03, 06 |
| F22 | Metric history charts and snapshot browser | P1 | 14 |
| F23 | Natural-language screens (Claude → Screen JSON, user confirms) | P2 | 13 |
| F24 | Hosting for Nexus, with auth and a scheduled refresh | P2 | 15 |
| F25 | "Open in Taproot" link | P2 | 12 (small add-on) |
| F26 | Insider buying signals (Form 4) | R | later |
| F27 | Point-in-time backtesting | R | 14 (spike only) |

## 2.3 Universe

**Default universe:**

- Every CIK with at least one ticker on **NYSE, Nasdaq, NYSE American or TXSE** (Texas Stock Exchange), from the SEC's `company_tickers_exchange.json`.
- **Excluded by default** (each is a toggleable chip):
  - SPACs and blank checks (SIC 6770)
  - Funds and trusts (SIC 6722, 6726)
  - Shell companies
  - OTC listings
  - CIKs with no XBRL financial facts
- **Included but labelled:**
  - Financials (Banks, Insurance, Capital Markets), with sector-specific n/m rules (§4.5)
  - REITs
  - Foreign private issuers (20-F/40-F filers)
- **Freshness rule:** a company whose latest annual report is more than 15 months old (configurable) is still included but flagged **STALE**. A universe toggle can exclude stale filers.
- **Share classes:** one row per company (CIK), not per ticker. GOOG and GOOGL are one company. The primary ticker is the most liquid listed class (from price data), and market cap sums all classes (§4.3).

**Universe controls in the UI:**

- Exchanges
- Sectors to include or exclude
- Kinds to exclude
- Include foreign filers
- Market cap min and max
- Average daily dollar volume min (default $1M)
- Maximum days since last filing

## 2.4 Metric library

**Conventions**

- **Units:** `usd` · `frac` (a fraction; 0.15 displays as 15.0%) · `pp` (percentage points, stored as a fraction: 0.02 = +2.0 pp) · `x` (a multiple) · `days` · `score` · `bool`.
- **Basis:**
  - `TTM` is the trailing twelve months of flows.
  - `MRQ` is the most recent balance-sheet instant.
  - `FY` is fiscal-year series.
  - Averages are `(now + 1 year ago) / 2` of balance-sheet items.
- **Tier:** `sec` means fundamentals only. `price` means it needs a market price, and those cells get a price as-of timestamp.
- **Better:** `↑` higher is better, `↓` lower is better, `·` neutral. This sets the direction in percentile ranking.
- **Null rules:** see "Null reason codes" at the end of this section.

### Size and liquidity

| id | Name | Definition | Unit | Better | Tier | P |
|---|---|---|---|---|---|---|
| `price` | Price | Last close | usd | · | price | P0 |
| `market_cap` | Market cap | Price × shares outstanding, all classes (§4.3) | usd | · | price | P0 |
| `enterprise_value` | Enterprise value | market_cap + total_debt + preferred + minority_interest − cash − st_investments | usd | · | price | P0 |
| `revenue_ttm` | Revenue (TTM) | Sum of the last 4 discrete quarters | usd | · | sec | P0 |
| `avg_dollar_volume_3m` | Avg $ volume (3m) | mean(close × volume) over the last 63 sessions | usd | ↑ | price | P0 |

### Valuation (all price tier)

| id | Name | Definition | Unit | Better | P |
|---|---|---|---|---|---|
| `pe_ttm` | P/E (TTM) | market_cap / net_income_ttm. Null if NI ≤ 0 | x | ↓ | P0 |
| `earnings_yield` | Earnings yield | net_income_ttm / market_cap (keeps negatives) | frac | ↑ | P0 |
| `ev_ebit` | EV/EBIT | EV / ebit_ttm. Null if EBIT ≤ 0 | x | ↓ | P0 |
| `ebit_ev` | EBIT/EV | ebit_ttm / EV. Null if EV ≤ 0 | frac | ↑ | P0 |
| `ev_ebitda` | EV/EBITDA | EV / ebitda_ttm. Null if ≤ 0 | x | ↓ | P0 |
| `ev_sales` | EV/Sales | EV / revenue_ttm | x | ↓ | P0 |
| `p_fcf` | P/FCF | market_cap / fcf_ttm. Null if FCF ≤ 0 | x | ↓ | P1 |
| `fcf_yield` | FCF yield | fcf_ttm / market_cap (keeps negatives) | frac | ↑ | P0 |
| `pb` | P/B | market_cap / equity. Null if equity ≤ 0 | x | ↓ | P0 |
| `dividend_yield` | Dividend yield | dividends_paid_ttm / market_cap | frac | ↑ | P0 |
| `buyback_yield` | Net buyback yield | (buybacks_ttm − stock_issued_ttm) / market_cap | frac | ↑ | P0 |
| `shareholder_yield` | Shareholder yield | dividend_yield + buyback_yield | frac | ↑ | P0 |
| `ncav_to_mcap` | NCAV / market cap | (current_assets − total_liabilities) / market_cap | frac | ↑ | P0 |

> **Design note: use yields, not multiples, to rank.** A P/E ratio breaks at zero and flips meaning below it. Yields (`earnings_yield`, `fcf_yield`, `ebit_ev`) run smoothly through zero, so losses rank last instead of disappearing. Presets rank on yields and display multiples.

### Profitability and returns (sec tier)

| id | Name | Definition | Unit | Better | P |
|---|---|---|---|---|---|
| `gross_margin` | Gross margin | gross_profit_ttm / revenue_ttm | frac | ↑ | P0 |
| `operating_margin` | Operating margin | ebit_ttm / revenue_ttm (EBIT = reported operating income) | frac | ↑ | P0 |
| `ebitda_margin` | EBITDA margin | ebitda_ttm / revenue_ttm (EBITDA = operating income + D&A) | frac | ↑ | P1 |
| `net_margin` | Net margin | net_income_ttm / revenue_ttm | frac | ↑ | P0 |
| `fcf_margin` | FCF margin | fcf_ttm / revenue_ttm (FCF = CFO − capex) | frac | ↑ | P0 |
| `roe` | ROE | net_income_ttm / avg equity. Null if avg equity ≤ 0 | frac | ↑ | P0 |
| `roa` | ROA | net_income_ttm / avg total_assets | frac | ↑ | P0 |
| `roic` | ROIC | nopat_ttm / avg invested_capital. NOPAT = EBIT × (1 − t). t = effective tax rate clamped to [0, 35%]; if pre-tax income ≤ 0, t = 21% with note `ASSUMED_TAX_RATE`. Invested capital = total_debt + equity + minority_interest − cash − st_investments; null if ≤ 0 | frac | ↑ | P0 |
| `greenblatt_roc` | Return on capital (Greenblatt) | ebit_ttm / (net_working_capital + net_ppe). NWC = (current_assets − cash − st_investments) − (current_liabilities − debt_current). Null if denominator ≤ 0 | frac | ↑ | P0 |
| `cash_conversion` | Cash conversion | cfo_ttm / net_income_ttm. Null if NI ≤ 0 | x | ↑ | P0 |
| `sbc_to_revenue` | SBC / revenue | sbc_ttm / revenue_ttm | frac | ↓ | P0 |
| `fcf_after_sbc_margin` | FCF after SBC margin | (fcf_ttm − sbc_ttm) / revenue_ttm | frac | ↑ | P1 |

### Growth (sec tier)

| id | Name | Definition | Unit | Better | P |
|---|---|---|---|---|---|
| `revenue_growth_yoy` | Revenue growth (YoY) | revenue_ttm / revenue_ttm_1y_ago − 1 | frac | ↑ | P0 |
| `revenue_cagr_3y` | Revenue CAGR (3y) | (rev_FY0 / rev_FY−3)^(1/3) − 1. Null if start ≤ 0 | frac | ↑ | P0 |
| `revenue_cagr_5y` | Revenue CAGR (5y) | Same, over 5 fiscal years | frac | ↑ | P1 |
| `eps_growth_yoy` | EPS growth (YoY) | Diluted EPS TTM vs 1 year ago. Null if prior ≤ 0 | frac | ↑ | P0 |
| `ebit_growth_yoy` | EBIT growth (YoY) | Null if prior ≤ 0 | frac | ↑ | P1 |
| `fcf_growth_yoy` | FCF growth (YoY) | Null if prior ≤ 0 | frac | ↑ | P1 |
| `gross_margin_change_yoy` | Gross margin change | gross_margin − gross_margin_1y_ago | pp | ↑ | P0 |
| `operating_margin_change_yoy` | Operating margin change | Same, for operating margin | pp | ↑ | P0 |
| `share_count_change_yoy` | Share count change | diluted_shares_latest_q / same quarter 1y ago − 1 | frac | ↓ | P0 |
| `rule_of_40` | Rule of 40 | revenue_growth_yoy + fcf_margin | frac | ↑ | P0 |

### Balance sheet and health

| id | Name | Definition | Unit | Better | Tier | P |
|---|---|---|---|---|---|---|
| `net_debt` | Net debt | total_debt − cash − st_investments (negative = net cash) | usd | ↓ | sec | P0 |
| `net_debt_to_ebitda` | Net debt / EBITDA | Null if EBITDA ≤ 0 | x | ↓ | sec | P0 |
| `debt_to_equity` | Debt / equity | total_debt / equity. Null if equity ≤ 0 | x | ↓ | sec | P0 |
| `current_ratio` | Current ratio | current_assets / current_liabilities | x | ↑ | sec | P0 |
| `quick_ratio` | Quick ratio | (cash + st_investments + receivables) / current_liabilities | x | ↑ | sec | P1 |
| `interest_coverage` | Interest coverage | ebit_ttm / interest_expense_ttm. Null if no interest expense is reported (note `NO_INTEREST_EXPENSE`) | x | ↑ | sec | P0 |
| `altman_z` | Altman Z (1968) | 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MktCap/TL + 1.0·Sales/TA. n/m for financials | score | ↑ | price | P1 |
| `cash_to_mcap` | Cash / market cap | (cash + st_investments) / market_cap | frac | ↑ | price | P0 |
| `goodwill_to_assets` | Goodwill + intangibles / assets | (goodwill + intangibles) / total_assets | frac | ↓ | sec | P1 |

### Efficiency and reinvestment (sec tier)

| id | Name | Definition | Unit | Better | P |
|---|---|---|---|---|---|
| `asset_turnover` | Asset turnover | revenue_ttm / avg total_assets | x | ↑ | P1 |
| `dso` | Days sales outstanding | receivables / revenue_ttm × 365 | days | ↓ | P1 |
| `dio` | Days inventory | inventory / cost_of_revenue_ttm × 365 | days | ↓ | P1 |
| `dpo` | Days payables | accounts_payable / cost_of_revenue_ttm × 365 | days | · | P1 |
| `cash_conversion_cycle` | Cash conversion cycle | dso + dio − dpo | days | ↓ | P1 |
| `capex_to_revenue` | Capex / revenue | capex_ttm / revenue_ttm | frac | · | P1 |
| `capex_to_dna` | Capex / D&A | capex_ttm / dna_ttm | x | · | P1 |

### Quality and accounting

| id | Name | Definition | Unit | Better | Tier | P |
|---|---|---|---|---|---|---|
| `piotroski_f` | Piotroski F-score | The 9 binary tests from Piotroski (2000), using the latest FY vs the prior FY. All 9 parts are stored for drill-down. n/m for banks and insurers | score | ↑ | sec | P0 |
| `accruals_ratio` | Accruals ratio (Sloan-style) | (net_income_ttm − cfo_ttm) / avg total_assets | frac | ↓ | sec | P0 |
| `payout_ratio` | Payout ratio | dividends_paid_ttm / net_income_ttm. Null if NI ≤ 0 | frac | · | sec | P1 |
| `fcf_payout_ratio` | FCF payout | dividends_paid_ttm / fcf_ttm. Null if FCF ≤ 0 | frac | ↓ | sec | P0 |
| `dps_no_cut_5y` | No dividend cut (5y) | True if dividends per share declared never fell by more than 1% year on year across the last 5 FYs. Null if fewer than 5 FYs or the tag is absent | bool | ↑ | sec | P0 |

### Price and momentum (price tier, price return only, excludes dividends)

| id | Name | Definition | Unit | Better | P |
|---|---|---|---|---|---|
| `return_1m` / `_3m` / `_6m` / `_12m` | Price return | Split-adjusted close vs close N sessions ago (21/63/126/252) | frac | · | P0 |
| `momentum_12_1` | 12–1 momentum | Return from t−252 to t−21 | frac | ↑ | P1 |
| `pct_from_52w_high` | Off 52-week high | close / max(close, 252 sessions) − 1 | frac | · | P0 |
| `volatility_1y` | Volatility (1y) | stdev(daily log returns, 252) × √252 | frac | ↓ | P1 |

### Data quality (always on)

| id | Name | Definition | Unit | P |
|---|---|---|---|---|
| `data_coverage` | Coverage | Share of the 20 core line items present for the latest TTM/MRQ | frac | P0 |
| `days_since_filing` | Days since last filing | Today − latest 10-K/10-Q/20-F/40-F filing date | days | P0 |
| `flag_count` | Flags | Number of active flags | score | P0 |

### Null reason codes (one per null cell, stored in `metric_notes`)

| Code | Shown as | Meaning |
|---|---|---|
| `MISSING_INPUT` | — | A required input isn't in the filings. The note names the input. |
| `NEGATIVE_DENOMINATOR` | n/m | For example P/E with a loss, or P/B with negative equity. |
| `NOT_APPLICABLE_SECTOR` | n/m | For example gross margin for a bank (§4.5). |
| `FOREIGN_PRICE_BASIS` | n/m | A foreign filer whose share basis or currency doesn't match the US price (until F20). |
| `INSUFFICIENT_HISTORY` | — | For example fewer than 4 quarters, or fewer than 252 price sessions. |
| `STALE_DATA` | — (with a STALE badge) | The inputs are older than the freshness limit. |
| `NO_INTEREST_EXPENSE` | n/m | No debt cost is reported. |
| `SMALL_PEER_GROUP` | — | A sector percentile was requested, but the sector has fewer than 5 companies in the universe. |
| `DERIVED_INPUT` | value plus ⓘ | Not a null: the value used a derived input (for example gross profit = revenue − COGS). |
| `ASSUMED_TAX_RATE` | value plus ⓘ | Not a null: ROIC used the 21% statutory rate (see the `roic` row). |
| `INPUT_EXCLUDES` | value plus ⓘ | Not a null: an input leaves out a known item the filing doesn't place (a finance lease whose balance-sheet line isn't stated). |

## 2.5 Filter comparators

| Comparator | Example | Notes |
|---|---|---|
| `gt` `gte` `lt` `lte` | ROIC ≥ 15% | Compared with a tolerance of 1e-9 |
| `between` | P/E between 8x and 20x | Inclusive |
| `eq` `neq` `in` | sector in [Technology, Industrials] | Categorical only |
| `is_null` `not_null` | Has a dividend yield | |
| `pct_rank_gte` / `pct_rank_lte` | Gross margin in the top 30% *of its sector* | `within`: `universe` or `sector`. Percentiles are computed **after universe filters, before other filters**. |
| `vs_sector_median_gte` / `_lte` | Operating margin ≥ sector median + 5 pp | For `frac` and `pp` units this is a difference; for others it's a ratio |

**Missing values:** each filter has `missing: "fail"` (default) or `"pass"`. The sieve counts companies removed *because of missing data* separately, so you can see when a filter is cutting on coverage rather than on substance.

## 2.6 Ranking

- **`percentile_composite` (default):**
  1. For each factor, take the direction-aware percentile within the ranking scope (`universe` or `sector`).
  2. Average the percentiles, weighted, over the factors that are present.
  3. If present factor weight is below `min_factor_coverage` (default 0.7), the score is null with `MISSING_INPUT`.
  4. Percentiles are computed on raw values, so outliers can't distort them. No winsorizing is needed for ranking.
- **`rank_sum`:** the sum of ordinal ranks, with the lowest sum best. This is Greenblatt's method.
- **Output:** `rank_score` plus `factor_contributions` per company, so the UI can show "ROIC contributed 0.41, FCF yield 0.33".
- **Tie-break:** ticker ascending, so output is deterministic.

## 2.7 Sieve and near misses

- **Sieve:** a sequential count after the universe step, then after each **top-level AND** filter in the user's order. An OR group counts as one step. Each step records `remaining`, `removed` and `removed_missing`.
- **Binding filter:** the step with the largest `removed`. The UI highlights it.
- **Near misses:** companies that pass the universe and **fail exactly one** top-level filter. Up to 25 are shown, sorted by how close they came: `|value − threshold| / |threshold|`, or the percentile gap. Each shows the failed filter, its value and the threshold. When the compared value is null, the near miss carries its reason code (`note`): the metric's own null reason, `SMALL_PEER_GROUP` when the sector is too small for a sector percentile or median, or `NEGATIVE_DENOMINATOR` when a ratio vs-median filter meets a sector median ≤ 0.

## 2.8 Presets

Every preset is a JSON file in `config/presets/` with `name`, `summary`, `kind` (`screen` or `red_flags`), `how_to_read`, `misses` (optional), `source`, `screen`. **Presets may use only P0 metrics**, so all 12 work in the MVP. Thresholds are starting points. WT-10 checks each one on real data, so it returns a workable list: not 0 names, not 2,000.

| id | Preset | Core logic (starting thresholds) | Source / lineage |
|---|---|---|---|
| `magic-formula` | Magic Formula | Exclude financials and utilities. Market cap ≥ $1B. `rank_sum` of `ebit_ev` and `greenblatt_roc`. Show the top 30 | Greenblatt, *The Little Book That Beats the Market* (2005) |
| `piotroski-value` | Piotroski value | `pb` in the cheapest 20% of the universe, `piotroski_f` ≥ 8 | Piotroski (2000), *Journal of Accounting Research* |
| `quality-compounders` | Quality compounders | `roic` ≥ 15%, `gross_margin` ≥ 40%, `revenue_cagr_3y` ≥ 8%, `net_debt_to_ebitda` ≤ 2 (missing passes), `fcf_margin` ≥ 10%. Ranked by roic and fcf_yield | Common quality-investing heuristics |
| `qarp` | Quality at a reasonable price | `roic` ≥ 12%, `fcf_yield` ≥ 4%, `operating_margin` in the top 40% of its sector | Common heuristic |
| `net-nets` | Graham net-nets | `ncav_to_mcap` ≥ 1.5 (that is, price ≤ ⅔ of NCAV). Includes a liquidity warning | Graham, *Security Analysis* / *The Intelligent Investor* |
| `shareholder-yield` | Shareholder yield | `shareholder_yield` ≥ 5%, `fcf_yield` > 0 | Faber, *Shareholder Yield* (2013). Glint's version excludes debt paydown, and the preset says so |
| `cash-rich-smallcaps` | Cash-rich small caps | Market cap $300M–$2B, `cash_to_mcap` ≥ 30%, `fcf_margin` > 0 | Heuristic |
| `margin-inflection` | Margin inflection | `operating_margin_change_yoy` ≥ +5 pp, `revenue_growth_yoy` > 0, `operating_margin` > 0 | Turnaround heuristic |
| `rule-of-40` | Rule of 40 (software) | Sector Technology, `rule_of_40` ≥ 40%, `revenue_ttm` ≥ $100M | SaaS industry heuristic |
| `dividend-durability` | Dividend durability | `dividend_yield` ≥ 3%, `fcf_payout_ratio` ≤ 70%, `net_debt_to_ebitda` ≤ 3, `dps_no_cut_5y` = true | Heuristic |
| `dilution-watch` | Dilution watch (red flags) | `share_count_change_yoy` ≥ 10% OR `sbc_to_revenue` ≥ 15% | Risk screen, not a buy list |
| `accruals-risk` | Accruals risk (red flags) | `accruals_ratio` in the top 10% of the universe AND `cash_conversion` < 0.5 | Sloan (1996), *The Accounting Review* |

Presets never claim returns. `how_to_read` explains what the screen looks for; `misses` lists what it misses, one line per blind spot.

## 2.9 Company drawer (quick view)

It opens from any result row:

- **Header:** name, tickers (all classes), exchange, sector (SIC description), filer type, fiscal year end and the "as of" stamps.
- **Key metrics:** grouped by category. Every cell has a tooltip with the formula, inputs and period, plus the null reason where there is one.
- **Sparklines:** revenue, operating margin, FCF and share count. These cover the last 10 FYs plus the last 12 TTM points.
- **Flags:** shown as questions, with evidence.
- **Sources:** the accession numbers of the filings used, linked to `https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/`.
- **Why it passed:** each filter, with the company's value and its sector percentile.
- **P2:** an "Open in Taproot" link, if `TAPROOT_URL` is set.

## 2.10 Flags (questions, not verdicts)

Thresholds live in `config/thresholds.yaml`.

| Flag id | Trigger (starting threshold) | Question shown |
|---|---|---|
| `dilution` | `share_count_change_yoy` ≥ 5% | "Share count is up X% in a year. What's driving the dilution?" |
| `earnings_without_cash` | NI > 0 and CFO < 0 for 2 consecutive FYs | "Profits are reported but operating cash flow is negative. Why is cash lagging earnings?" |
| `receivables_outpacing` | DSO up ≥ 20% YoY while revenue growth is < 10% | "Customers are taking longer to pay. Is revenue quality changing?" |
| `inventory_build` | Inventory growth exceeds revenue growth by ≥ 20 pp | "Inventory is growing much faster than sales. Is demand slowing?" |
| `goodwill_heavy` | `goodwill_to_assets` ≥ 50% | "Over half the assets are goodwill and intangibles. How were the acquisitions priced?" |
| `thin_coverage` | `interest_coverage` < 2x | "EBIT covers interest less than twice. How exposed is it to rates or a downturn?" |
| `stale_filing` | `days_since_filing` > 15 months, for the annual report | "The latest annual report is over 15 months old. Is the company late or delisting?" |
| `late_filer` | NT 10-K or NT 10-Q in the last 12 months | "The company filed a late-filing notice. What delayed it?" |
| `negative_equity` | equity ≤ 0 | "Equity is negative. Is that buybacks or accumulated losses? (P/B and ROE are n/m.)" |
| `heavy_sbc` | `sbc_to_revenue` ≥ 15% | "Stock comp is over 15% of revenue. What are FCF and margins after SBC?" |
| `restated` (P1) | A past period's value changed in a later filing by > 1% | "Prior figures were revised. What changed?" |
| `fy_change` | Fiscal year end changed in the last 2 years | "Fiscal year end changed. Are periods comparable?" |

## 2.11 Data freshness

Every page shows: `Fundamentals: SEC bulk file of <date, 03:00 ET> · Prices: close of <date> · Build <id, timestamp>`. Each company shows its latest filing date. Price-tier cells get a tooltip with the price date.

## 2.12 Export and sharing

- **CSV:** visible columns, plus `as_of_fundamentals`, `as_of_prices` and `notes` (null reasons). The filename is `glint-<screen-slug>-<YYYY-MM-DD>.csv`.
- **URL:** the full Screen JSON is compressed into a `?s=` parameter (lz-string). Opening the link restores the screen exactly.

## 2.13 Natural-language screens (v2, WT-13)

Example: "profitable small-cap semis with net cash and rising margins" → Claude → Screen JSON → shown as **editable filter chips**. It runs only after you press Apply.

**Guardrails:**

- Claude sees only metric ids, names, units and definitions from the registry.
- The output is validated against the Screen schema. Unknown ids are rejected, with one retry, then a clear failure.
- Claude never supplies numbers about companies.
- Unit sanity: "margin above 20%" must become `0.20`, and the eval set checks this.
- The feature is hidden when `ANTHROPIC_API_KEY` isn't set.

## 2.14 Saved screens, watchlists, diffs (v1, WT-12)

- Saved screens and watchlists live in `data/user.duckdb`, which the pipeline never touches.
- **Run history:** each saved screen keeps its results per build.
- **Diff:** "since last run: +4 entered, −2 left". Each change shows *which* filter changed state.
- **Watchlist view:** your tickers with their flags and the metric changes since you added them.

## 2.15 Why there are no backtests in the MVP

An honest backtest needs three things the MVP doesn't have:

1. **Point-in-time fundamentals.** You may only use facts *filed* before each test date. Companyfacts includes a `filed` date, so this is possible but non-trivial.
2. **Delisted companies.** The current ticker file drops dead companies. Leaving them out is **survivorship bias**, and it makes every value screen look better than it was.
3. **Prices for delisted tickers.** The free tiers mostly don't have them.

**The plan:**

- Archive the full metric snapshot **every build from day one** (F17). In 6–12 months you'll have genuine point-in-time history for free.
- WT-14 runs a research spike on rebuilding history from `filed` dates and writes up whether a credible backtest is possible.
- Until then, the UI never shows "this screen returned X%".

---

# Part 3: UX and design

## 3.1 Pages

| Route | Purpose |
|---|---|
| `/` | The screener: universe bar, filter panel, sieve, results, near misses, drawer |
| `/presets` | Preset gallery with a card per preset (summary, how to read, source, "Open") |
| `/metrics` | Metric dictionary, generated from `config/metrics.yaml`: search, category tabs, a formula and inputs for each metric, and a worked example on a real ticker |
| `/company/[ticker]` | Full-page version of the drawer (shareable) |
| `/about` | Methodology, data sources and tiers, limits, survivorship disclaimer, "not investment advice" |
| `/saved` (v1) | Saved screens, run history, diffs, watchlists |

## 3.2 Main screen layout (wireframe)

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ◆ GLINT  [US · NYSE+Nasdaq · ex-SPAC/funds · ≥$300M · ≥$1M/day ▾]  [Presets ▾]  [⤓] [🔗] │
│ Fundamentals: SEC file of <date> 03:00 ET · Prices: close <date> · Build <id>          │
├──────────────────────┬───────────────────────────────────────────────────────────────┤
│ FILTERS          [+] │ SIEVE  Universe N₀ ─▶ ROIC N₁ ─▶ FCF yld N₂ ─▶ ND/EBITDA N₃ ─▶ ◆ N │
│ ┌──────────────────┐ │        (binding filter highlighted; "−k missing" shown per step) │
│ │ ROIC  ≥ 15%    ✕ │ ├───────────────────────────────────────────────────────────────┤
│ │ ▁▂▅█▆▃▂▁ ▲ hist  │ │ #  Ticker  Name          Sector     Mkt cap   ROIC  FCF yld  … ⚑ │
│ └──────────────────┘ │ 1  ····    ············  ·········  ·······   ····  ·····    2 │
│ ┌──────────────────┐ │ 2  ····    ············  ·········  ·······   ····  ·····    0 │
│ │ FCF yield ≥ 5%   │ │ …  (virtualized rows; "—" missing, "n/m" not meaningful)       │
│ └──────────────────┘ │                                                               │
│ ┌ OR ──────────────┐ │                                                               │
│ │ Rev growth ≥ 5%  │ │                                                               │
│ │ Op margin Δ ≥+2pp│ │                                                               │
│ └──────────────────┘ ├───────────────────────────────────────────────────────────────┤
│ RANK BY              │ NEAR MISSES (failed exactly one filter) ▸ 23                   │
│ ROIC ······ 50%      │  ···· failed FCF yield: 4.8% vs ≥ 5.0%                         │
│ FCF yield · 50%      │                                                               │
│ within: universe ▾   │                                                               │
└──────────────────────┴───────────────────────────────────────────────────────────────┘
          Educational tool. Not investment advice.          [Drawer slides in from the right ▶]
```

## 3.3 Interaction rules

**Number formatting.** This is centralized in one `format.ts`, so nothing else formats numbers.

| Unit | Format |
|---|---|
| `frac` | `15.2%` |
| `pp` | `+2.3 pp` |
| `x` | `14.2x` |
| `usd` | `$1.24B` / `$312M` |
| `days` | `47 d` |
| `score` | `7/9`, or 2 decimal places |

Tables use tabular numerals.

**Null display.** A missing value shows "—" and a not-meaningful one shows "n/m". Both have a tooltip naming the reason code in plain English.

**Threshold input:**

- You type in display units ("15" for 15%). The UI converts to a fraction exactly once, in `units.ts`.
- A histogram of the metric's distribution in the current universe sits under the input, with the threshold marker and a "N companies pass" counter.

**Keyboard:**

| Key | Action |
|---|---|
| `/` | Focus metric search |
| `f` | Add a filter |
| `Esc` | Close the drawer |
| `j` / `k` | Move between rows |
| `Enter` | Open the drawer |

**URL state.** Every change updates `?s=` (debounced), and the back button undoes a filter change.

**States:**

- **Loading:** a skeleton plus the sieve's previous counts, dimmed.
- **Empty result:** show the sieve and near misses, plus "Loosen the binding filter: <name>".
- **API down:** a clear banner. The last results are kept, greyed out.
- **No build yet:** "Run `glint refresh` first" with the command.

**Mock mode** (UI development, WT-05): a fixed amber banner reading "SYNTHETIC DATA: NOT REAL COMPANIES" on every page. All mock tickers start with `SYN`.

## 3.4 Visual direction (proposal, to be finalized in WT-05 → `docs/DESIGN.md`)

**Concept: "the sluice."** The market is a riverbed. Filters are sieve trays, and what survives catches the light. The sieve bar is drawn as stacked trays that narrow at each step, with counts on each tray. Results that newly entered since your last run get a single soft glint shimmer (once only, and never with reduced motion).

| Token | Use | Proposed value |
|---|---|---|
| `bg` | Page | Near-black slate `#0E1114` |
| `surface` | Panels | Wet stone `#171C21` |
| `surface-2` | Raised and hover | `#202830` |
| `line` | Dividers | `#2C343C` |
| `text` | Primary text | Quartz `#E8E6E1` |
| `text-muted` | Secondary | `#9AA3AB` |
| `accent` | Glints, focus, primary actions | Gold `#E3B341` |
| `accent-2` | Links, secondary | River teal `#3C8D93` |
| `pos` / `neg` | Up and down values | Green and red pairs tuned for color-blind safety. **Never color alone**: always a sign or arrow too |
| `warn` | Stale, mock banner | Amber |

- **Type:** a crisp grotesk for the UI (Geist or Inter), and a mono for formulas and tickers (Geist Mono or JetBrains Mono). Tabular numerals in all tables.
- **Density:** a compact/comfortable toggle. The default is compact, at 32 px rows.
- **Light theme:** required (quartz background, slate text, darker gold).
- **Motion:** 150–200 ms ease-out. Only the sieve and new-entrant glint animate, and `prefers-reduced-motion` turns both off.
- **Charts:** Recharts sparklines. The palette has to pass a color-blind check. No 3D, no gradients on data.

## 3.5 Accessibility

- Everything is reachable by keyboard, with visible focus rings in the accent color.
- Text meets 4.5:1 contrast against its surface.
- Tooltips can be opened from the keyboard and are announced. The table has proper `th` scope and sorts with `aria-sort`.
- No information depends on color alone.

---

# Part 4: Data

## 4.1 Sources and tiers

| Tier | Source | What it gives | Access rules | Refresh |
|---|---|---|---|---|
| 1 | SEC `companyfacts.zip` (`https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip`) | All XBRL facts for all filers (us-gaap, ifrs-full, dei) | No key. **A User-Agent with contact details is required.** The ceiling is **10 req/s**; this is one download | Rebuilt nightly, about 03:00 ET |
| 1 | SEC `submissions.zip` (`https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`) | Company metadata (SIC, state, fiscal year end, tickers, exchanges) and filing history (forms, dates, accession numbers) | As above | Nightly |
| 1 | SEC `company_tickers_exchange.json` | CIK ↔ ticker ↔ exchange | As above | Daily |
| 1 | SEC per-company APIs (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, `.../submissions/CIK##########.json`) | Used **only** for test fixtures and spot checks, never for the full universe | Through the gateway, ≤ 8 req/s | On demand |
| 2 | **Massive** (formerly Polygon.io; renamed 30 Oct 2025) grouped-daily bars | OHLCV for every US ticker on one date in **one call**, plus splits | Free "Stocks Basic": **5 calls/min**, end-of-day only. Past days are available after midnight ET, and the current day returns 403. Check the history depth on your plan | Daily |
| 2 (fallback) | `yfinance` (unofficial Yahoo wrapper) | Daily history per ticker | No key. Unofficial, can rate-limit or break. Personal and educational use only | Daily |

**Rules:**

- Tier 1 numbers are never overwritten by tier 2.
- Price-based metrics always show the price date.
- A price-provider failure makes price-tier metrics null (`MISSING_INPUT: price`). **It never stops the screen running on fundamentals.**

**Backfill arithmetic (free Massive plan):**

- One trading year is about 252 grouped-daily calls, which takes about 51 minutes at 5 calls a minute.
- Run the backfill once, overnight. After that, 1 call a day.

## 4.2 Pipeline

```
           ┌────────────────────┐  ┌────────────────────┐  ┌───────────────────┐
download → │ companyfacts.zip   │  │ submissions.zip    │  │ tickers_exchange  │   GLINT_RAW_DIR/sec/<date>/
           └─────────┬──────────┘  └─────────┬──────────┘  └─────────┬─────────┘
extract  →   facts_raw (parquet;    companies (meta, filings,   ticker map (canonical
             whitelisted tags only) SIC→sector, kinds)          symbols, share classes)
                     │                       │                        │
normalize →  financials (FY / Q / TTM / instant series per line item, with source tag + accession)
                     │
prices   →   prices_daily (grouped daily) → price_stats (returns, 52w, vol, ADV)
                     │
metrics  →   metrics_snapshot (wide: 1 row per company) + metric_notes + metric_history
             + flags + quality  →  archive snapshot to GLINT_RAW_DIR/snapshots/date=<d>/
                     │
publish  →   data/builds/<build_id>.duckdb  →  data/current.json points to it (atomic swap)
                     │
serve    →   FastAPI (read-only connection) → Next.js UI
```

## 4.3 XBRL normalization rules (the hard part; WT-03 owns it)

1. **Identify periods by `start`/`end` dates, never by `fy`/`fp`.** In companyfacts, `fy` and `fp` describe the *filing* a fact appeared in, not the period it measures. A FY2025 10-K also carries FY2024 and FY2023 comparatives tagged `fy=2025`.
2. **Classify each duration by its length in days:**

   | Length | Class |
   |---|---|
   | 80–100 | Quarter |
   | 170–190 | Half year |
   | 260–285 | 9 months |
   | 350–380 | Fiscal year (covers 52/53-week years) |

   Instants are balance-sheet items.
3. **Deduplicate.** The same `(line item, start, end)` appears in many filings.
   - The **current view** keeps the value from the latest `filed` filing, which picks up restatements.
   - Store the earliest-filed value as well (`first_filed_value`, `first_filed_date`). This feeds the restatement flag (F21) and future point-in-time work.
4. **Tag precedence.** Each line item has an ordered tag list (Appendix B). Per company and period, use the highest-priority tag that has a value. Record `source_tag` and `source_accn`.
   - Coverage reports show which tags are doing the work.
   - Never sum alternative tags.
5. **Discrete quarters:**
   - Use 3-month facts where they exist.
   - Otherwise derive Q2 = H1 − Q1 and Q3 = 9M − H1.
   - **Q4 = FY − 9M** (Q4 is never filed on its own).
   - Mark derived quarters `derived=true`.
6. **TTM for flows:**
   - TTM is the sum of the last 4 discrete quarters, which must have contiguous end dates.
   - If a quarter can't be built, TTM = FY + year-to-date − the prior year's year-to-date of the same length (for example FY2025 + 6M 2026 − 6M 2025). This is the same arithmetic over filed cumulative values. The span must be fiscal-year length and must not straddle a fiscal-year change. Otherwise TTM is null (`INSUFFICIENT_HISTORY`).
   - If the latest period is a fiscal year, TTM = FY.
   - Check: TTM at a fiscal year end must equal FY within 0.5%, or log a warning.
7. **Instants:** use the value at the latest period end (MRQ). For averages, use the instant nearest to one year earlier (within ±45 days).
8. **Sign conventions:** capex, dividends and buybacks are tagged as **positive payments**, so subtract them explicitly. Losses are negative. Write a test for each.
9. **Derived line items** (each flagged `DERIVED_INPUT`):

   | Item | Derivation |
   |---|---|
   | `gross_profit` | revenue − cost_of_revenue |
   | `total_liabilities` | `LiabilitiesAndStockholdersEquity` − `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`. `Liabilities` is often untagged. |
   | `total_debt` | debt_current + debt_noncurrent. If only `LongTermDebt` exists, it already *includes* the current portion, so don't add `LongTermDebtCurrent` on top. Operating lease liabilities are **excluded** from debt; this is a stated definition. |
   | `ebitda` | operating_income + D&A from the cash-flow statement |
   | `fcf` | cfo − capex |

10. **Units:**
    - Monetary facts carry an ISO currency unit (`USD`, `TWD`, `EUR`…). EPS is `USD/shares` and share counts are `shares`.
    - Reject a fact whose unit doesn't match the line item's expected kind.
    - The reporting currency is the most common currency on revenue facts.
11. **Share count** (for market cap), in priority order:
    1. `dei:EntityCommonStockSharesOutstanding`, the latest cover-page value, with its date.
    2. `us-gaap:CommonStockSharesOutstanding`.
    3. `WeightedAverageNumberOfDilutedSharesOutstanding`, with note `DERIVED_INPUT`.

    **Multi-class companies** (GOOG/GOOGL, BRK.A/BRK.B):
    - WT-01 must check what companyfacts actually contains for them. Per-class cover-page values may be dimensional and so missing from the API.
    - MVP rule: if a single total is available and classes trade at about the same price, use total × primary price. Otherwise use a manual entry in `config/share_classes.yaml` (class, conversion ratio, reason).
12. **Splits:** if a split happened between the share-count date and the price date, the market cap is wrong. Detect it using the provider's split data and either adjust the shares (stating the ratio) or null with a note.
13. **Foreign filers (20-F/40-F):**
    - These are often IFRS (`ifrs-full`) and may report in non-USD currency, while the US listing may be an ADR that represents N ordinary shares.
    - **MVP:** fundamentals-only metrics (margins, growth, returns, health) are fine. Price-based metrics are null with `FOREIGN_PRICE_BASIS`, *unless* the reporting currency is USD and the listed shares are the ordinary shares.
    - **v1 (F20):** FX rates plus an ADR ratio table.
14. **Fiscal year changes:** detect a fiscal-year-end change from `submissions` and the duration pattern. Never build a TTM that straddles a transition period. Flag `fy_change`.

## 4.4 Sectors

- Glint uses the **SIC code** from SEC `submissions`, mapped into Glint sectors via `config/sectors.yaml` (Appendix C).
- This is **not GICS**, which is licensed by MSCI/S&P. The UI says "Sector (SIC-based)".
- SIC codes are assigned at registration and can be stale, so `config/sector_overrides.yaml` allows a manual override (`ticker → sector`, with a reason). Every override shows up in the methodology page.

## 4.5 Applicability matrix (n/m rules)

| Metric group | Banks | Insurance | Capital Markets | REITs | Utilities | Foreign (MVP) |
|---|---|---|---|---|---|---|
| Gross margin, DIO/DPO/CCC | n/m | n/m | n/m | ok | ok | ok |
| EV-based (EV/EBIT, EBIT/EV, EV/EBITDA, EV/Sales), net debt/EBITDA | n/m | n/m | n/m | ok (note: FFO not available) | ok | n/m* |
| Current/quick ratio | n/m | n/m | n/m | ok | ok | ok |
| ROIC, Greenblatt ROC | n/m | n/m | n/m | ok | ok | ok |
| Altman Z | n/m | n/m | n/m | n/m | ok | n/m* |
| Piotroski F | n/m | n/m | ok | ok | ok | ok |
| P/E, P/B, ROE, dividend metrics | ok | ok | ok | ok (note: P/E is a weak REIT measure) | ok | n/m* |

\* Until F20 lands. The matrix lives in `config/metrics.yaml` (`applicability`) and is enforced in WT-06.

## 4.6 Data quality

- **`data_coverage`:** the share of 20 core line items present.
  - Flows: revenue, cost_of_revenue, operating_income, pretax_income, income_tax, net_income, cfo, capex, d&a, sbc.
  - Instants: cash, current_assets, total_assets, current_liabilities, total_liabilities, total_debt, equity, receivables, inventory, shares_outstanding.
- **`days_since_filing`** and the STALE badge.
- **Audit rules** (`glint audit`, WT-06) print outliers for review and never auto-fix them. Examples:
  - Gross margin outside [−1, 1]
  - Market cap > $6T
  - Revenue TTM ≠ FY at a fiscal year end
  - Equity jumps of more than 10x
  - Share count jumps of more than 3x without a split
- **Run report** (WT-07): coverage per line item compared with the previous build. A drop of more than 2 pp is a warning.

## 4.7 Storage (DuckDB + Parquet)

- **Raw data** lives in `GLINT_RAW_DIR` (default `~/GlintData/raw`), outside the repo, shared by every worktree.
- **Builds** live per checkout in `GLINT_DB_DIR` (default `./data`).
- **User data** is `data/user.duckdb`, which the pipeline never touches.

| Table | Key | Columns (main) |
|---|---|---|
| `companies` | cik | name, tickers[], primary_ticker, exchange, sic, sic_description, sector, state_of_inc, fiscal_year_end, filer_category, kind (operating/spac/fund/shell/no_common_equity), is_foreign_filer, taxonomy, reporting_currency, last_annual_date, last_quarterly_date, nt_filing_12m, fy_end_changed, is_up_c, up_c_evidence, finance_lease_status, finance_lease_evidence |
| `facts_raw` (parquet) | — | cik, taxonomy, tag, unit, start, end, val, accn, fy, fp, form, filed, frame |
| `financials` | cik, line_item, basis, period_end | period_start, value, unit, source_tag, source_accn, filed, first_filed_value, first_filed_date, derived |
| `prices_daily` (parquet) | ticker, date | open, high, low, close, volume, vwap |
| `price_stats` | ticker, as_of | close, return_1m…12m, momentum_12_1, high_52w, pct_from_52w_high, volatility_1y, avg_dollar_volume_3m, history_days |
| `metrics_snapshot` | cik | as_of_fundamentals, as_of_prices, ticker, name, sector, kind, + one column per metric id |
| `metric_notes` | cik, metric_id | code, message |
| `metric_history` | cik, metric_id, basis, period_end | value |
| `flags` | cik, flag_id | question, evidence (json) |
| `pipeline_runs` | run_id | started, finished, status, stage_durations (json), counts (json), source_timestamps (json), warnings (json) |
| `user.saved_screens` (v1) | id | name, screen_json, created, updated |
| `user.screen_runs` (v1) | screen_id, build_id | tickers[], counts |
| `user.watchlists` (v1) | id, ticker | added_at, note |

**Schema versioning:** `contracts/db.py` holds `DB_SCHEMA_VERSION`. A build records it. If the API finds a mismatch, it refuses to serve the build and says "rebuild".

## 4.8 Refresh schedule

- The SEC bulk files are rebuilt about **03:00 ET**, which is usually 08:00 London (07:00 in the week or two when US and UK clocks change on different dates).
- Massive serves the prior day's bars from just after midnight ET.
- **Schedule the refresh at 09:15 London** (launchd on your Mac, WT-07, optional). Manual `glint refresh` always works.
- **Runtime targets** (to measure, then record the real numbers):

  | Run | Target |
  |---|---|
  | Cold full build (excluding the first price backfill) | ≤ 30 min |
  | Warm nightly | ≤ 10 min |
  | Rebuild from raw without downloading | ≤ 5 min |

## 4.9 Licensing and use

- SEC data is public. Respect the fair-access policy: User-Agent, rate limits, and bulk files over per-company scraping.
- **Massive and Yahoo data is licensed for *your* use.** Before sharing Glint with Nexus members or hosting it (WT-15), read the provider's terms on display and redistribution. Upgrade or switch provider if you need to.
- Don't commit price data or bulk SEC files to git. Small trimmed fixtures are fine.

---

# Part 5: Architecture and tech stack

## 5.1 Stack decision

**The decision:** a Python data engine with a FastAPI API, and a Next.js (TypeScript) UI, in one monorepo.

| Layer | Choice | Why |
|---|---|---|
| Env and deps | **uv** (`pyproject.toml` + lockfile) | Fast and reproducible. It's your Python default. |
| Warehouse and transforms | **DuckDB** + **Parquet** | Embedded and very fast for analytics. SQL window functions handle percentiles and sector medians. No server to run. |
| Dataframes | **polars** (no pandas in engine code) | Fast and strict about types. One dataframe library, not two. |
| Validation and contracts | **pydantic v2** (+ pydantic-settings) | One source of truth that generates JSON Schema and OpenAPI. |
| HTTP | **httpx** + **tenacity** + **aiolimiter** | The SEC gateway: User-Agent, throttle, retries. |
| Parsing | **orjson** | Streaming thousands of JSON files out of the zip. |
| CLI | **typer** + **rich** | A CLI per feature, with readable tables in the terminal. |
| API | **FastAPI** + uvicorn | Typed, and generates OpenAPI automatically. |
| Search | **rapidfuzz** | A fuzzy fallback after exact and prefix matches. |
| Quality | **ruff**, **pyright (strict)**, **pytest** | Same bar as Taproot. |
| UI | **Next.js (App Router) + React + TypeScript strict** (`noUncheckedIndexedAccess`), **Tailwind** with tokens | Your proven web stack from Taproot. |
| UI data | **openapi-typescript** + **openapi-fetch**, **TanStack Query**, **TanStack Table + Virtual**, **Recharts**, **lz-string** | Types are generated from the API contract, so they never drift. Virtualized tables handle thousands of rows. |
| UI tests | **Vitest**, **Playwright** | Unit plus end-to-end. |
| LLM (v2) | **anthropic** SDK, with the model set by an env var | NL screens only. |

**Alternatives I rejected:**

- **Streamlit only.** It's fastest to start, but it can't deliver the table UX, URL state or design quality you'll want. It also hits a ceiling quickly.
- **All TypeScript, like Taproot.** It works, but bulk XBRL processing and analytics are much more natural in Python with DuckDB and polars.

**The honest trade-off:** two toolchains (uv and npm) mean more setup and two CI jobs. The contract-generation step (5.3) is what keeps that manageable.

## 5.2 Repo layout

```
glint/
├── CLAUDE.md                     # conventions, commands, gotchas (Appendix A)
├── README.md                     # quickstart
├── Makefile                      # setup, check, test, contracts, dev, refresh
├── .env.example                  # every variable, commented
├── .worktreeinclude              # .env, web/.env.local → copied into new worktrees
├── .gitignore                    # data/, .env*, .venv, node_modules, web/.next, .claude/worktrees/
├── .github/workflows/ci.yml
├── config/
│   ├── metrics.yaml              # metric registry (ids, defs, units, applicability, status)
│   ├── concepts.yaml             # line item → ordered XBRL tags (Appendix B)
│   ├── sectors.yaml              # SIC ranges → Glint sectors (Appendix C)
│   ├── sector_overrides.yaml
│   ├── share_classes.yaml
│   ├── thresholds.yaml           # flag thresholds, audit rules, freshness limits, tolerances
│   └── presets/*.json
├── contracts/
│   ├── openapi.json              # GENERATED from FastAPI — never hand-edit
│   └── screen.schema.json        # GENERATED from pydantic
├── engine/
│   ├── pyproject.toml  uv.lock
│   ├── glint/
│   │   ├── cli.py                # registers all sub-apps (pre-wired in WT-00)
│   │   ├── core/                 # settings, paths, errors, logging, http gateway, cache, filelock
│   │   ├── contracts/            # pydantic: screen DSL, api models, metric defs, enums, db DDL
│   │   ├── ingest/sec/           # WT-01
│   │   ├── universe/             # WT-01
│   │   ├── ingest/prices/        # WT-02
│   │   ├── financials/           # WT-03
│   │   ├── screen/               # WT-04
│   │   ├── metrics/  flags/  quality/   # WT-06
│   │   ├── pipeline/             # WT-07
│   │   ├── api/                  # WT-08 (routers pre-wired in WT-00)
│   │   ├── fixtures/             # WT-00 (real trimmed fixtures + synthetic generator)
│   │   └── smoke/                # WT-09
│   └── tests/
│       ├── fixtures/sec/*.json   # real, trimmed, committed
│       ├── golden/golden_values.csv
│       └── <module>/test_*.py
├── web/
│   ├── package.json
│   ├── src/app/…                 # routes
│   ├── src/components/…
│   ├── src/lib/api/types.ts      # GENERATED from contracts/openapi.json
│   ├── src/lib/{format,units,url}.ts
│   ├── mocks/                    # synthetic JSON for mock mode
│   └── e2e/                      # Playwright
├── docs/
│   ├── SPEC.md                   # Parts 1–7 of this plan
│   ├── DESIGN.md
│   ├── methodology.md
│   ├── metrics.md                # GENERATED from config/metrics.yaml
│   ├── STATUS.md                 # worktree tracker (Part 8.9)
│   ├── decisions/                # one file per worktree: WT-00.md … + CONTRACTS.md
│   └── worktrees/                # WT-00-foundation.md … (Part 9 briefs)
└── data/                         # gitignored: builds/, current.json, user.duckdb
```

## 5.3 Contracts (what parallel work depends on)

**Contract-first is the whole trick that makes parallel worktrees possible.** WT-00 defines these, and changing them needs the protocol in §8.6.

| Contract | Lives in | Consumers |
|---|---|---|
| Screen DSL (pydantic) → `contracts/screen.schema.json` | `engine/glint/contracts/screen.py` | 04, 05, 08, 10, 12, 13 |
| API request and response models → `contracts/openapi.json` → `web/src/lib/api/types.ts` | `engine/glint/contracts/api.py` | 05, 08, 09 |
| Metric definition model plus the registry file | `contracts/metrics.py` + `config/metrics.yaml` | 04, 05, 06, 10 |
| Enums: `LineItem`, `Sector`, `Kind`, `NoteCode`, `Unit`, `Basis`, `Tier` | `contracts/enums.py` | everyone |
| DB DDL plus `DB_SCHEMA_VERSION` | `contracts/db.py` | 01, 02, 03, 06, 07, 08 |
| Stage interface (`Stage`, `StageResult`, `BuildContext`) | `contracts/pipeline.py` | 01, 02, 03, 06, 07 |

`make contracts` regenerates the JSON Schema, the OpenAPI and the TypeScript types. CI fails if regenerating produces a diff.

## 5.4 Screen DSL (v1)

```json
{
  "dsl_version": 1,
  "name": "Quality at a fair price",
  "universe": {
    "exchanges": ["NYSE", "Nasdaq", "NYSE American"],
    "sectors_include": [],
    "sectors_exclude": ["Banks", "Insurance"],
    "exclude_kinds": ["spac", "fund", "shell", "no_common_equity"],
    "include_foreign_filers": true,
    "include_stale": false,
    "market_cap_min": 300000000,
    "market_cap_max": null,
    "avg_dollar_volume_min": 1000000
  },
  "filters": {
    "op": "and",
    "children": [
      { "metric": "roic", "cmp": "gte", "value": 0.15 },
      { "metric": "fcf_yield", "cmp": "gte", "value": 0.05 },
      { "metric": "net_debt_to_ebitda", "cmp": "lte", "value": 2.0, "missing": "pass" },
      { "metric": "gross_margin", "cmp": "pct_rank_gte", "value": 0.7, "within": "sector" },
      { "op": "or", "children": [
          { "metric": "revenue_growth_yoy", "cmp": "gte", "value": 0.05 },
          { "metric": "operating_margin_change_yoy", "cmp": "gte", "value": 0.02 }
      ]}
    ]
  },
  "rank": {
    "method": "percentile_composite",
    "within": "universe",
    "factors": [ { "metric": "roic", "weight": 0.5 }, { "metric": "fcf_yield", "weight": 0.5 } ],
    "min_factor_coverage": 0.7
  },
  "columns": ["ticker", "name", "sector", "market_cap", "roic", "fcf_yield", "net_debt_to_ebitda"],
  "sort": { "by": "rank_score", "dir": "desc" },
  "limit": 100,
  "near_misses": true
}
```

**Validation rules** (WT-00 defines them, WT-04 enforces them):

- Metric ids must exist in the registry with status `live`.
- Each comparator must be allowed for the metric's unit (no `in` on numbers, no `pct_rank` on `bool`).
- `between` takes `[lo, hi]` with lo ≤ hi.
- Groups nest at most 3 deep.
- Weights must be > 0.
- `limit` must be ≤ 1000.
- `sort.then` adds up to 2 tie-breaking `{by, dir}` keys after `sort.by`; keys are unique, nulls sort last for each, and ticker ascending breaks what's left.
- **All percentages are fractions.**

## 5.5 API

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/health` | `{status, build_id}` | |
| GET | `/api/meta` | As-of stamps, build id, universe counts, universe rules (stale threshold), source timestamps, last run status | Drives the header |
| GET | `/api/metrics` | Registry (live metrics with definitions) | |
| GET | `/api/sectors` | Sectors with counts | |
| GET | `/api/presets`, `/api/presets/{id}` | Preset list and detail | |
| POST | `/api/screen` | `{as_of, universe_count, funnel[], total, results[], near_misses[], warnings[]}` | p95 < 300 ms |
| POST | `/api/screen/export` | CSV stream | |
| GET | `/api/distribution?metric=&within=&sector=` | Histogram bins plus percentiles for the current universe | For the threshold UI |
| GET | `/api/search?q=` | Ticker and name matches | exact → prefix → fuzzy |
| GET | `/api/companies/{ticker}` | Snapshot, notes, flags, history, sources, why-passed (if `screen` is passed) | 404 `UNKNOWN_TICKER`, 200 with `kind` for excluded kinds |
| GET | `/api/companies/{ticker}/history?metric=` | Series | |
| (v1) | `/api/screens…`, `/api/watchlists…` | CRUD, runs, diffs | WT-12 |
| (v2) | `POST /api/nl-screen` | Draft Screen JSON plus explanation | WT-13 |

**Error model:**

- Expected states return `{error: CODE, message}`:
  - 404 `UNKNOWN_TICKER`
  - 422 `INVALID_SCREEN`, with the field path
  - 503 `NO_BUILD` / `SCHEMA_MISMATCH`
- Only real failures return 500.
- Every response carries `build_id`.

## 5.6 Configuration (`.env.example`)

```bash
# Required by SEC fair-access policy: identify yourself with a contact address
GLINT_SEC_USER_AGENT="Glint research tool you@example.com"
GLINT_SEC_MAX_RPS=8                   # stay under SEC's 10 req/s ceiling

# Data locations
GLINT_RAW_DIR=~/GlintData/raw         # shared by all worktrees (downloads, prices, snapshots)
GLINT_DB_DIR=./data                   # per checkout (builds, current.json, user.duckdb)

# Prices
GLINT_PRICE_PROVIDER=massive          # massive | yfinance
MASSIVE_API_KEY=                      # optional; without it Glint falls back to yfinance and says so
MASSIVE_CALLS_PER_MIN=5               # free Stocks Basic plan

# Ports (override per worktree, see Part 8)
GLINT_API_PORT=8000
NEXT_PUBLIC_GLINT_API_URL=http://localhost:8000
NEXT_PUBLIC_GLINT_MOCK=0              # 1 = synthetic data with banner

# v2 only
ANTHROPIC_API_KEY=
GLINT_LLM_MODEL=
TAPROOT_URL=
```

The app must run in a degraded mode when optional keys are missing, and it must say why.

## 5.7 Cross-cutting rules

- **Single gateway per source.** Every SEC request goes through `core/http.py`, which handles the User-Agent, the throttle, retries on 429/5xx/network errors, and conditional GET with ETag/Last-Modified. Every price request goes through the `PriceProvider` interface. Nothing calls the network anywhere else.
- **Pure core, impure edges.** Period logic, metric formulas, the DSL compiler and ranking are pure functions with unit tests.
- **Scoped errors.** One failing source degrades its own metrics, never the whole build or page.
- **Logging:** structured, one line per stage with counts and duration. No print debugging in committed code.
- **File lock:** writers to `GLINT_RAW_DIR` take `raw.lock` (in `core/filelock.py`), so two worktrees can't download at once.
- **Determinism:** the same raw inputs produce byte-identical metric snapshots (stable sorts, no reliance on dict order). There's a test for it.

## 5.8 Testing strategy

| Layer | What | Where | In CI? |
|---|---|---|---|
| Unit | Period engine, TTM, every metric formula, DSL compiler, ranking, formatting and units (TS) | `engine/tests/*`, `web/src/**/*.test.ts` | ✅ |
| Fixture | Real, trimmed companyfacts and submissions for the test tickers (Appendix D) | `engine/tests/fixtures/sec/` | ✅ |
| Golden | Hand-verified values from filings (`ticker, item, period_end, expected, unit, accn, where_in_filing, verified_by, verified_on`), tolerance 0.5% | `engine/tests/golden/` | ✅ |
| Contract | Responses validate against OpenAPI; generated types are in sync | `engine/tests/api/`, CI step | ✅ |
| Property | Results always satisfy filters; sieve counts never increase; near misses fail exactly one filter | `engine/tests/screen/` | ✅ |
| Live (opt-in) | Real SEC and price calls, marked `@pytest.mark.live` | anywhere | ❌ (manual) |
| Audit | Distribution sanity checks on a full build | `glint audit` | ❌ (manual, each release) |
| Smoke | Every preset plus company lookups for the test tickers, on a real build; exits non-zero on failure | `glint smoke` | ❌ (manual, each release) |
| E2E | Playwright: load, apply a preset, open the drawer, export CSV, share URL | `web/e2e/` | ✅ against mock mode; ❌ against a real build |

**Tests never touch the network or real data directories.** Fixtures go in a temp dir per test.

## 5.9 CI (GitHub Actions)

On push and on PRs to `main`, three jobs run in parallel:

1. **engine:** `uv sync --frozen` → `ruff check` → `ruff format --check` → `pyright` → `pytest -m "not live"`
2. **web:** `npm ci` → `tsc --noEmit` → `eslint` → `vitest run` → `playwright test` (mock mode)
3. **contracts:** `make contracts` → `git diff --exit-code contracts/ web/src/lib/api/types.ts`

## 5.10 Performance budgets

| Thing | Budget |
|---|---|
| `POST /api/screen`, full universe, 10 filters, with near misses | p95 < 300 ms |
| `GET /api/companies/{t}` | p95 < 150 ms |
| UI: apply a filter → table updated | < 500 ms perceived |
| Table scroll, 2,000 rows | 60 fps (virtualized) |
| Peak memory during extraction | < 2 GB |

---

# Part 6: Roadmap and milestones

Sizes: **S** is about one focused Claude Code session plus review. **M** is 2–4 sessions. **L** is 5 or more. These are rough; record the real effort in `docs/STATUS.md` to calibrate.

| Milestone | Worktrees | Exit criteria |
|---|---|---|
| **M0 Foundation** | WT-00 (L) | CI green. Contracts, stubs, fixtures and synthetic data are merged. `glint --help` lists every command. |
| **M1 Data spine** | WT-01 (M), WT-02 (M), WT-03 (L) | `glint universe --summary`, `glint price AAPL` and `glint financials AAPL` are all correct on the test set. |
| **M2 Engine and shell** | WT-04 (M), WT-05 (L) | Screens run end to end in the UI on synthetic data (mock mode). |
| **M3 Real metrics and API** | WT-06 (L), WT-07 (M), WT-08 (M) | `glint refresh` builds a real snapshot, and the API serves it. |
| **M4 MVP v0.1** | WT-09 (M), WT-10 (S–M), WT-11 (M) | All §1.7 criteria are met. Tag `v0.1.0`. |
| **M5 v1** | WT-12 (M), WT-14 (M), F20/F21 follow-ups | Saved screens, diffs and history are in use. |
| **M6 v2** | WT-13 (M), WT-15 (M) | NL screens, and a hosted version only if Nexus needs it. |

**Critical path:** WT-00 → WT-03 → WT-06 → WT-07 → WT-09 → WT-11. Put your attention there first. Everything else fits around it.

**Rule:** don't start Wave 4 until you've used v0.1 for real for 2 weeks. That's how you'll know which v1 features actually matter.

---

# Part 7: Risks, failure modes and pre-mortem

*Pre-mortem: "It's March 2027 and Glint was abandoned. Why?"*

| # | Failure mode | How it shows up | Likelihood | Impact | Mitigation | Tripwire |
|---|---|---|---|---|---|---|
| R1 | **XBRL rabbit hole**: chasing 100% tag coverage | WT-03 runs past 3× its size estimate | High | High | Ordered tag lists, coverage reports, and acceptance at ≥ 90% core coverage. Null-with-reason is a valid outcome. | Coverage gains below 1 pp per session → stop and move on |
| R2 | **Silently wrong numbers** (units, signs, double-counted debt, wrong period) | A plausible but wrong ROIC in a Nexus pitch | Medium | Very high | Golden values, internal consistency checks (TTM = FY), `glint audit`, visible sources | Any golden failure blocks a merge |
| R3 | **Price provider breaks or changes terms** | Price metrics go null; yfinance gets blocked | Medium | Medium | The `PriceProvider` interface with two implementations, and screens that still run on fundamentals | Two consecutive failed price stages → switch provider |
| R4 | **Merge hell from parallel worktrees** | Long rebases; contracts changed in two places | Medium | High | Contract-first, an ownership map, pre-wired stubs, a cap of 3 active worktrees, daily rebase | Any rebase over 30 min → pause new worktrees |
| R5 | **Scope creep**: 16 worktrees and v2 features before the MVP is used | Lots of half-done branches | High | High | Waves are gates. The MVP is WT-00 to WT-11 only. Run the 2-week usage rule. | More than 3 open worktrees, or Wave 4 started before v0.1 |
| R6 | **Shallow reviews** because Claude writes fast | Bugs found weeks later | Medium | High | The acceptance checklist goes in the PR, a fresh-context review subagent runs, and you hand-check 2–3 numbers per PR | Two post-merge bugs from one worktree → add tests before continuing |
| R7 | **Financials and foreign filers ranked against everyone else** | Banks top an EV/EBIT screen | High (without the matrix) | Medium | The applicability matrix, `FOREIGN_PRICE_BASIS`, and a sector-relative option | Any n/m metric appearing in ranking output is a bug |
| R8 | **Survivorship and look-ahead misread as performance** | "This screen beat the market" | Medium | High | No backtests in the MVP, disclaimers, and snapshot archiving | Any returns claim in the UI or presets is a bug |
| R9 | **Performance and memory** on the full companyfacts file | Extraction takes over 1 hour or the Mac swaps | Medium | Medium | Stream from the zip, whitelist tags, write Parquet in batches, measure | Above 2× the budget → profile before adding features |
| R10 | **Stale data you don't notice** | Screens on last month's prices | Medium | Medium | As-of stamps everywhere, the STALE badge, and the run report in the header | Build older than 3 days → banner |
| R11 | **Lost user data** on a rebuild | Saved screens vanish | Low | High | `user.duckdb` is separate and the pipeline never opens it in write mode. A test enforces this. | — |
| R12 | **SEC throttling or blocking** | 403s from sec.gov | Low | Medium | The gateway with a User-Agent at ≤ 8 req/s, and bulk files rather than per-company calls | Any 403 → stop and check the User-Agent and rate |
| R13 | **Your time**: term, trips, applications | Weeks with no progress, and lost context | High | Medium | Every worktree is mergeable on its own, `docs/STATUS.md` holds where you were, and briefs are self-contained | — |
| R14 | **Ticker mapping errors** (BRK.B vs BRK-B, share classes) | Missing or duplicated companies | Medium | Medium | Canonical symbol rules, a share-class config, and an unmatched-ticker report | Unmatched NYSE/Nasdaq tickers above 5% |
| R15 | **Licensing** when sharing with Nexus | A terms breach | Low | Medium | Check the terms in WT-15 before any hosting | — |

---

# Appendices

## Appendix B: XBRL concept map (starter for `config/concepts.yaml`)

Tags are in priority order. The IFRS column is a starting point, so **WT-03 verifies it against TSM** and extends it from coverage reports.

| Line item | Kind | us-gaap (in priority order) | ifrs-full (verify) |
|---|---|---|---|
| revenue | duration | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`, `SalesRevenueGoodsNet`, `RevenuesNetOfInterestExpense` | `Revenue`, `RevenueFromContractsWithCustomers` |
| cost_of_revenue | duration | `CostOfRevenue`, `CostOfGoodsAndServicesSold`, `CostOfGoodsSold`, `CostOfServices` | `CostOfSales` |
| gross_profit | duration | `GrossProfit` → else derived | `GrossProfit` |
| operating_income | duration | `OperatingIncomeLoss` | `ProfitLossFromOperatingActivities` |
| pretax_income | duration | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`, `IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments` | `ProfitLossBeforeTax` |
| income_tax | duration | `IncomeTaxExpenseBenefit` | `IncomeTaxExpenseContinuingOperations` |
| net_income | duration | `NetIncomeLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic`, `ProfitLoss` (*includes minority interest: flag it*) | `ProfitLossAttributableToOwnersOfParent`, `ProfitLoss` (flag) |
| interest_expense | duration | `InterestExpense`, `InterestExpenseNonoperating`, `InterestExpenseDebt` | `FinanceCosts` |
| dna | duration | `DepreciationDepletionAndAmortization`, `DepreciationAndAmortization`, `DepreciationAmortizationAndAccretionNet` | `DepreciationAndAmortisationExpense` |
| sbc | duration | `ShareBasedCompensation`, `AllocatedShareBasedCompensationExpense` | `AdjustmentsForSharebasedPayments` |
| rnd | duration | `ResearchAndDevelopmentExpense` | `ResearchAndDevelopmentExpense` |
| sga | duration | `SellingGeneralAndAdministrativeExpense` | `SellingGeneralAndAdministrativeExpense` |
| eps_diluted | duration | `EarningsPerShareDiluted` | `DilutedEarningsLossPerShare` |
| diluted_shares | duration | `WeightedAverageNumberOfDilutedSharesOutstanding` | `AdjustedWeightedAverageShares` |
| cfo | duration | `NetCashProvidedByUsedInOperatingActivities`, `NetCashProvidedByUsedInOperatingActivitiesContinuingOperations` | `CashFlowsFromUsedInOperatingActivities` |
| capex | duration (+ outflow) | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets` | `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities` |
| dividends_paid | duration (+ outflow) | `PaymentsOfDividends`, `PaymentsOfDividendsCommonStock` | `DividendsPaidClassifiedAsFinancingActivities` |
| buybacks | duration (+ outflow) | `PaymentsForRepurchaseOfCommonStock` | `PaymentsToAcquireOrRedeemEntitysShares` |
| stock_issued | duration | `ProceedsFromIssuanceOfCommonStock`, `ProceedsFromStockOptionsExercised` | `ProceedsFromIssuingShares` |
| dps_declared | duration | `CommonStockDividendsPerShareDeclared`, `CommonStockDividendsPerShareCashPaid` | (none reliable; null) |
| cash | instant | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` (*includes restricted: flag it*) | `CashAndCashEquivalents` |
| st_investments | instant | `ShortTermInvestments`, `MarketableSecuritiesCurrent`, `AvailableForSaleSecuritiesDebtSecuritiesCurrent` | `CurrentFinancialAssetsAtFairValueThroughProfitOrLoss` (verify) |
| receivables | instant | `AccountsReceivableNetCurrent` | `TradeAndOtherCurrentReceivables` |
| inventory | instant | `InventoryNet` | `Inventories` |
| current_assets | instant | `AssetsCurrent` | `CurrentAssets` |
| total_assets | instant | `Assets` | `Assets` |
| ppe_net | instant | `PropertyPlantAndEquipmentNet` | `PropertyPlantAndEquipment` |
| goodwill | instant | `Goodwill` | `Goodwill` |
| intangibles | instant | `IntangibleAssetsNetExcludingGoodwill` | `IntangibleAssetsOtherThanGoodwill` |
| accounts_payable | instant | `AccountsPayableCurrent` | `TradeAndOtherCurrentPayables` |
| current_liabilities | instant | `LiabilitiesCurrent` | `CurrentLiabilities` |
| total_liabilities | instant | `Liabilities` → else derived (§4.3 rule 9) | `Liabilities` |
| debt_current | instant | `LongTermDebtCurrent`, `DebtCurrent`, `ShortTermBorrowings`, `CommercialPaper` (*sum the distinct ones; WT-03 decides and documents*) | `ShorttermBorrowings`, `CurrentPortionOfLongtermBorrowings` (verify) |
| debt_noncurrent | instant | `LongTermDebtNoncurrent`; else `LongTermDebt` (which *includes* the current portion, so don't add debt_current) | `LongtermBorrowings` (verify) |
| preferred | instant | `PreferredStockValue` | — |
| minority_interest | instant | `MinorityInterest` | `NoncontrollingInterests` |
| equity | instant | `StockholdersEquity` | `EquityAttributableToOwnersOfParent` |
| equity_incl_nci | instant | `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` | `Equity` |
| liabilities_and_equity | instant | `LiabilitiesAndStockholdersEquity` | `EquityAndLiabilities` |
| retained_earnings | instant | `RetainedEarningsAccumulatedDeficit` | `RetainedEarnings` |
| shares_outstanding | instant | `dei:EntityCommonStockSharesOutstanding`, `CommonStockSharesOutstanding`, then diluted weighted (flag) | `dei:EntityCommonStockSharesOutstanding` |

## Appendix C: SIC → Glint sector (starter for `config/sectors.yaml`)

**Glint sectors:** Technology · Communication · Consumer Discretionary · Consumer Staples · Health Care · Industrials · Materials · Energy · Utilities · Real Estate · Banks · Insurance · Capital Markets · Unclassified.

These are starter ranges. WT-01 checks them against the SEC SIC code list, splits ranges where needed, and verifies them with the Appendix D tickers. **Where ranges overlap, the narrower range or specific code wins.**

| SIC | Sector | Notes |
|---|---|---|
| 0100–0999 | Consumer Staples | Agriculture |
| 1000–1099, 1400–1499 | Materials | Metal and nonmetal mining |
| 1200–1299, 1311, 1381–1389 | Energy | Coal, oil and gas, field services |
| 1500–1799 | Industrials | Construction |
| 2000–2199 | Consumer Staples | Food, beverages, tobacco |
| 2200–2399, 2500–2599 | Consumer Discretionary | Textiles, apparel, furniture |
| 2400–2499, 2600–2699 | Materials | Lumber, paper |
| 2700–2799 | Communication | Publishing |
| 2800–2829, 2850–2899 | Materials | Chemicals (excluding pharma, soaps) |
| 2833–2836 | Health Care | Pharma, biotech |
| 2840–2844 | Consumer Staples | Soaps, cosmetics |
| 2900–2999 | Energy | Petroleum refining |
| 3000–3299 | Materials | Rubber, plastics, glass, stone |
| 3300–3399 | Materials | Primary metals |
| 3400–3569, 3580–3599 | Industrials | Fabricated metal, machinery |
| 3570–3579 | Technology | Computers |
| 3600–3659, 3690–3699 | Industrials | Electrical equipment |
| 3660–3679 | Technology | Comms equipment, semiconductors, components |
| 3710–3716, 3750–3799 | Consumer Discretionary | Motor vehicles, other transport equipment |
| 3720–3729, 3760–3769 | Industrials | Aerospace and defense |
| 3800–3839, 3860–3899 | Technology / Industrials | Instruments: check case by case |
| 3840–3851 | Health Care | Medical devices |
| 3900–3999 | Consumer Discretionary | Misc. manufacturing |
| 4000–4799 | Industrials | Transportation |
| 4800–4899 | Communication | Telecom, broadcasting, cable |
| 4900–4949, 4960–4991 | Utilities | Electric, gas, water |
| 4950–4959 | Industrials | Waste and sanitary services |
| 5000–5199 | Industrials | Wholesale |
| 5200–5399, 5500–5999 | Consumer Discretionary | Retail |
| 5400–5499 | Consumer Staples | Food stores |
| 6000–6199 | Banks | Banks and credit institutions |
| 6200–6299 | Capital Markets | Brokers, exchanges, asset managers |
| 6300–6411 | Insurance | |
| 6500–6553 | Real Estate | |
| 6798 | Real Estate | REITs (`is_reit=true`) |
| 6722, 6726, 6770 | (kind: fund or spac) | Excluded by default |
| 7000–7099 | Consumer Discretionary | Hotels |
| 7200–7299 | Consumer Discretionary | Personal services |
| 7370–7379 | Technology | Software and IT services |
| 7300–7369, 7380–7399 | Industrials | Business services |
| 7800–7899 | Communication | Motion pictures, entertainment |
| 7900–7999 | Consumer Discretionary | Recreation |
| 8000–8099 | Health Care | Health services |
| 8700–8799 | Industrials | Engineering and management services (biotech labs under 8731: check) |
| other | Unclassified | Shown with a warning in the coverage report |

## Appendix D: test tickers (fixtures and acceptance)

| Ticker | Why it's in the set |
|---|---|
| AAPL | Clean US-GAAP, September FY, large buybacks |
| MSFT | June FY |
| NVDA | 52/53-week FY ending late January, fast growth |
| KO | December FY, consumer staples, dividends |
| MU | Cyclical, recent losses, August/September FY |
| KHC | Large goodwill and impairments |
| RIVN | Loss-maker: negative EBIT, NI and FCF |
| SBUX | Negative equity |
| XOM | Energy, large capex |
| F | Captive finance arm, so debt and EV look extreme. Tests flags, not fixes |
| JPM | Bank: n/m rules |
| O | REIT |
| BRK.B / BRK.A | Two share classes at very different prices |
| GOOGL / GOOG | Two share classes at similar prices, one CIK |
| TSM | 20-F, IFRS, TWD, ADR |
| ASML | 20-F, EUR. Check whether its XBRL is us-gaap or ifrs-full and record it |
| (SPAC) | Picked at fixture time from current SIC 6770 filers |
| (recent IPO) | Picked at fixture time: fewer than 8 quarters of XBRL history |
| (FY change) | Picked at fixture time, if one is findable via submissions |

## Appendix E: glossary

| Term | Meaning |
|---|---|
| XBRL | The machine-readable tagging in SEC filings. Each number is a "fact" with a tag, unit, period and filing. |
| CIK | The SEC's permanent company ID. Tickers change; CIKs don't. |
| Accession number | The ID of one filing (for example `0000320193-25-000079`). It's how Glint links to sources. |
| us-gaap / ifrs-full / dei | Taxonomies: US accounting tags, international accounting tags, and cover-page tags. |
| Duration vs instant | Flows cover a period (revenue). Balances are a point in time (cash). |
| TTM / MRQ / FY | Trailing twelve months, most recent quarter (balance sheet), fiscal year. |
| pp | Percentage points: the difference between two percentages. |
| n/m | Not meaningful: a value exists in principle, but this formula breaks for this company. |
| EV | Enterprise value = equity value + debt + preferred + minority interest − cash. |
| NOPAT / ROIC | Operating profit after tax, and the return it earns on the capital invested. |
| Survivorship bias | Testing only companies that still exist, which flatters results. |
| Look-ahead bias | Using information that wasn't public yet on the test date. |
| Point-in-time (PIT) | Data exactly as it was known on a past date. |
| Worktree | A separate checkout and branch of the same repo, so parallel Claude sessions don't collide. |
| Contract | A shared shape (DSL, API model, DB schema) that parallel work depends on. It changes only by protocol. |

## Appendix F: sources (checked 28 Oct 2026)

- [SEC: EDGAR Application Programming Interfaces](https://www.sec.gov/page/sec-api-documentation): bulk `companyfacts.zip` and `submissions.zip` URLs, rebuilt nightly around 03:00 ET, and the frames API.
- [SEC: Accessing EDGAR Data](https://www.sec.gov/os/accessing-edgar-data): the 10 requests/second ceiling and the User-Agent with a contact address.
- [Claude Code docs: Run parallel sessions with worktrees](https://code.claude.com/docs/en/worktrees): `--worktree`, `.claude/worktrees/`, `worktree-<name>` branches, `.worktreeinclude`, base branch, cleanup and subagent isolation.
- [Massive knowledge base: Free Basic plan timing](https://massive.com/knowledge-base/article/on-the-free-basic-plan-when-can-i-pull-the-previous-trading-days-data): 5 requests/min, end-of-day, previous days only.
- [FISD: Polygon.io is now Massive](https://fisd.net/polygon-io-is-now-massive): renamed effective 30 Oct 2025, with existing APIs and accounts continuing to work.
- [QVeris free stock API comparison (updated Aug 2026)](https://api.qveris.ai/guides/stock-api-free-comparison): context on free-tier limits across providers.
- Preset lineage (books and papers, no links needed):
  - Greenblatt, *The Little Book That Beats the Market* (2005)
  - Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers," *Journal of Accounting Research* (2000)
  - Sloan, "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?", *The Accounting Review* (1996)
  - Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," *Journal of Finance* (1968)
  - Graham, *The Intelligent Investor*
  - Faber, *Shareholder Yield* (2013)

*End of plan.*
