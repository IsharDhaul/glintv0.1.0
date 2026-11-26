# Glint v0.1.0 release notes

Fundamentals-first US stock screener: SEC XBRL filings (tier 1), end-of-day prices (labelled
tier 2), every metric with its formula, inputs, period basis and unit. Educational tool, not
investment advice.

Release build: `20261124T170400Z`. SEC bulk files are of 2026-11-24 and prices run to 2026-11-23,
the last completed session. The build is a `--no-download` rebuild on main with #84–#88, after
the full refresh `20261124T152302Z` (same raw data); both are reported in `data/reports/`. Main
also has #89, merged after the build: the universe panel names the stale-report window from
`/api/meta` ("in the last 15 months"). It changes wording only, not numbers.

## §1.7 success criteria

| Criterion | Evidence | Status |
|---|---|---|
| One command (`glint refresh`) rebuilds everything; if it fails, the previous build stays live | Full refresh `20261124T152302Z`: every stage ok, 651 s; release build `20261124T170400Z` (no download): every stage ok, 429 s, no warnings; build-then-swap with an atomic pointer (`pipeline/swap.py`, `tests/pipeline/test_runner.py`), kill test (WT-07) | ✅ |
| Universe built, real counts by exchange, sector and kind recorded | `glint universe --summary` on the release build, below | ✅ |
| Every P0 metric live and shows its definition | 52 of 52 P0 metrics `live` (71 in the registry, all with definition, inputs, basis, unit); `docs/metrics.md`; shown in the picker, column ⓘ and /metrics. The UI shows Glint's line items, not XBRL tags (known-limits) | ✅ |
| Core-metric coverage ≥ 90% (non-financial US-GAAP 10-K filers, last 15 months); real figure recorded | `glint financials --coverage`, default universe domestic non-financials (n = 3,415; the default universe already leaves out annual reports older than 15 months): **83.8%** at TTM/MRQ, 84.6% at the latest FY (83.6% on 2026-10-30; the same on the 2026-11-23 build). Gaps by reason: MISSING_INPUT 14,333, INSUFFICIENT_HISTORY 3,647, NOT_APPLICABLE_SECTOR 2,822 | ❌ below target; recorded, and v0.1.0 ships with it (user decision 2026-11-23: the spec calls this "a target to measure; the real figure gets recorded"); raising it is v1 work |
| `POST /api/screen` p95 < 300 ms, full universe, 10 filters | `glint smoke --perf` on the release build: p50 55.8 ms, **p95 69.3 ms**, 40 runs, 10 filters with near misses (company page p95 13.0 ms, budget 150). Measured with other sessions loading the machine; 53.7 ms on the 2026-11-23 build | ✅ |
| 30 golden values hand-checked against filings, passing in tests | `engine/tests/golden/golden_values.csv`, `tests/golden/test_golden_filings.py`: **30 of 30** filled and passing (10 companies × revenue, net income, total assets: MSFT, JPM, MU, SBUX, O, KHC, GOOGL, RIVN, BRK.B, TSM), each equal to Glint's value. How they were read, as `verified_by` records it: all 30 read from the filing by Claude (claude.ai) and confirmed by the user ("claude-chat, confirmed by Ishar"), not read by the user alone; the four older rows no person had checked (WAT, AVEX, DUOL, POWI) were rechecked the same way. The CSV's 70 rows: 36 verified by the user, 34 by claude-chat with the user's confirmation; `lookup --pending` and `--recheck` list nothing | ✅ (with the reading method stated) |
| 12 presets working, each with its definition and source | `glint smoke --perf` 45/45 on the release build (43 smoke checks plus 2 timing checks; every preset runs); each preset JSON has `summary`, `how_to_read`, `source` | ✅ |
| Every null in the snapshot has a reason code (enforced by a test) | `tests/metrics/test_stage.py::test_every_null_has_exactly_one_reason` (fixture build); release build checked directly: 309,816 null cells across 71 metrics, **0** without a reason code, 0 with two, 0 with only an info note. Not enforced at build time (known-limits) | ✅ |
| Used for one real Nexus idea-generation session; what was missing logged | Deferred for the 27 Nov internship submission; to be run with Nexus members after. Until then the v1 priority list below is built from `docs/known-limits.md` (user decision 2026-11-26) | ⏸ deferred to v0.1.1 |

## The numbers

- **Universe:** 7,988 companies with a ticker; default universe 5,218 (4,130 domestic, 1,088
  foreign). Left out: not on a default exchange 1,958, not an operating company 703, no XBRL
  facts 109. By kind across all 7,988: operating 7,199, fund 429, SPAC 336, no listed common
  stock 24. Exchanges include TXSE (10, all in the default universe). Up-Cs in the default
  universe: 99 (67 more on the review list, `glint universe --up-c-candidates`).
- **Coverage (core mean of 20 line items, default universe):** domestic non-financial 83.8%
  (TTM/MRQ) / 84.6% (FY); financial 59.1% / 59.8%; foreign 82.1% / 81.8%. Lowest domestic
  items at TTM/MRQ: inventory 54.8%, cost of revenue 61.2%, total debt 61.7%, receivables 64.8%,
  capex 73.0% (inventory and receivables are absent for many service businesses).
- **P0 null rates, domestic non-financials (n = 3,415):** enterprise value 42.7% (48.0% on
  2026-10-31), net debt 40.7%, debt/equity 47.5%, ROIC 65.8%, interest coverage 50.7%, P/E 50.8%
  (mostly NEGATIVE_DENOMINATOR, losses), gross margin 38.0%, market cap 1.2%, price 0.1%.
- **Refresh timings:** full refresh 651 s (download_sec 196 s, extract_facts 187 s, financials
  221 s, companies 34 s, metrics 10 s); `--no-download` rebuild 429 s (it re-extracted facts for #88's new tags). The 2026-11-23 build took
  2,743 s, nearly all the one-off re-fetch of every cover page and the older 10-Ks after #55.
- **Screen latency:** p95 69.3 ms (budget 300 ms); company page p95 13.0 ms (budget 150 ms).
- **Changes since the 2026-11-23 build:** sector overrides (MELI, EBAY, ETSY to Consumer
  Discretionary; NUTX to Health Care; PYPL to Technology; #79, #86); Strive and Great Elm priced
  at their common stock (#84: ASST $7.76B → $1.31B at the time; #87: GEG $765M → $64M);
  share-count history ends at the headline count (#85: last point equals the headline for all
  4,788 companies with one); IFRS bonds as non-current debt where borrowings aren't tagged, and
  TSMC's bonds and current financial assets summed from its 20-F (#88: TSM ROIC FY2024 51.3% →
  39.1%; snapshot metrics changed for 15 companies, all IFRS filers).

## Verification

- Golden values: 30 filing values (10 companies × revenue, net income, total assets) plus the
  earlier hand-checked rows, all passing (see §1.7 for how each was read); 20 metric spot-checks (`tests/golden/spot_checks.csv`), **all 20 agree** with Glint to rounding
  (`tests/golden/test_spot_checks.py`). They were recomputed in code by Claude (claude.ai) from the
  inputs and components Glint lists, and confirmed by the user. That checks formulas and
  definitions; the inputs that are also golden rows were read from the filings. The questions they
  raised led to #88 (IFRS bonds and short-term investments; TSM ROIC 51.3% → 39.1%; FY-history
  wording) and to two known limits (restricted cash; 58 IFRS bond filers).
- Full review against SPEC §1.5 and §1.7 (a separate read-only reviewer, given the code and the SPEC):
  no P0. Fixed before v0.1.0 in #72: late-filer and fiscal-year-change rules now read
  `config/thresholds.yaml` (they had been hard-coded), and flag questions are built from their own
  thresholds, with one stale-filing number (principle 8). Deferred to v1, listed in
  `docs/known-limits.md`: accounting standard not shown, XBRL tags not in the UI, universe
  defaults in code, excluded shown as a total, null-reason rule enforced only in tests, verdict-like
  preset wording (WT-11.md 2026-11-23).

## Known limits

See `docs/known-limits.md`.

## v1 priority list

Built from `docs/known-limits.md`, not from real use: the Nexus session is deferred to v0.1.1 and
will reorder this list. Ordered by impact: how many companies a limit touches and how far it moves
a number.

1. **Restricted cash noted on the cell.** 604 default-universe companies (SBUX among them) tag only
   cash including restricted cash, so their net debt, EV and cash/market cap count it with no
   note. Show the note `concepts.yaml` already asks for.
2. **A freshness limit on share-count change.** `share_count_change_yoy` uses the latest diluted
   count however old it is: about 170 companies use a count more than a year older than their TTM
   end (REG's is from 2020).
3. **IFRS bonds for the 58 filers.** Debt may be understated for 58 default-universe IFRS filers
   that tagged bonds or notes since 2025: NMG and HITI, where bonds exceed borrowings; NAK, TURB,
   SPRC, NXE, QUCY, LCFY and the banks, which tag no borrowings. Each needs its own balance-sheet
   check, as TSMC had in #88.
4. **CHS and NRUC priced at a non-common listing.** Neither has a common listing, and Glint
   prices a company at its most liquid SEC ticker, which for them is a preferred or note. Detecting these symbols from the
   cover needs a new companies.parquet column (a contract change); ASST and GEG were fixed by hand
   (#84, #87).
5. **GOOGL D&A is depreciation only.** GOOGL tags no amortization line, so its D&A, and with it
   EBITDA and net debt/EBITDA, leave amortization out (spot-check SC14, `tests/golden/spot_checks.csv`).
   Check which other filers do the same.
6. **Shift-click secondary sort.** The API supports `sort.then` (#80); the UI isn't wired to it
   yet. This is a convenience, and it changes no number.
