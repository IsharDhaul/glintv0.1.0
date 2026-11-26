# Glint

**A fundamentals-first stock screener for US-listed companies, where every number can be traced
back to the SEC filing it came from.**

Glint screens about 5,200 US-listed companies. For each screen it shows how many companies each
filter removes (the *sieve*), ranks the survivors, and lists the *near misses*: companies that
failed one filter, and by how much. Glint computes every ratio itself from SEC XBRL filings, and
each one comes with its formula, inputs, period and unit.

*Educational tool. Not investment advice.*

<!-- Screenshot: the screener with a preset applied (sieve, results table, near misses).
     Save as docs/images/screener.png, then replace this comment with:
     ![The screener: filters on the left, the sieve and results on the right](docs/images/screener.png) -->

## Why it exists

Free screeners are fast, but their numbers are hard to trust or defend. Glint answers four
problems with them:

| Problem with typical screeners | What Glint does instead |
|---|---|
| Ratios come from a data vendor, with no formula shown. Is "P/E 14" TTM or forward, GAAP or adjusted? | It computes every ratio from the company's own SEC filings and shows the formula, the XBRL tags, the period (TTM, FY or latest quarter) and the source filing. |
| You get a list, not a reason. | The **sieve** shows the count after every filter, so you can see which one does the real cutting. |
| Hard cut-offs hide good ideas: ROIC of 14.9% vanishes from a "≥ 15%" screen. | The **near misses** panel lists companies that failed exactly one filter, with the gap. |
| Some ratios are meaningless in some sectors (gross margin for a bank), but show up anyway. | Those cells read **n/m** (not meaningful), with the reason. A missing value reads **—**, also with a reason. Glint never fills in or estimates a number. |

## Principles

1. **If a number matters, it comes from the source document.** SEC XBRL filings come first;
   market prices are a separate, labelled source; AI never supplies numbers.
2. **State the definition.** Every metric shows its formula, inputs, period basis and unit.
3. **Never fabricate.** A missing value is null with a reason code: no estimates, no fills, no
   silent zeros.
4. **Questions, not verdicts.** Warning flags are phrased as questions, with the evidence
   attached.
5. **Universe honesty.** The screen always says which companies it leaves out, and why.

## Try it in two minutes (no keys, no downloads)

Mock mode runs the whole interface on a **synthetic** dataset in your browser. The companies
aren't real, and a banner says so. You need [Node.js](https://nodejs.org/) 22 or later.

```bash
git clone https://github.com/IsharDhaul/GlintOfficialv0.1.0.git glint
cd glint/web
npm ci
NEXT_PUBLIC_GLINT_MOCK=1 npm run dev
```

Open <http://localhost:3000>.

## How to use it

1. **Start from a preset.** Open **Presets** and pick one, for example *Quality compounders* or
   *Magic Formula*. Each preset card says what the screen looks for, how to read the results and
   what the screen misses.
2. **Read the sieve.** Each step shows how many companies are left after that filter, how many it
   removed, and how many it removed only because the value was missing.
3. **Adjust the filters.** Drag a threshold on a filter's histogram, or press `f` to add a filter.
   The counts update as you go, and the URL holds the whole screen, so you can share it as a link.
4. **Check the near misses.** These companies failed one filter, grouped by the filter and showing
   the gap. "Include" adds them back.
5. **Open a company.** Press `Enter` on a result for the quick view, or `o` for the full page. It
   shows every metric with its sector median and percentile, history over time, and the
   red-flag checks phrased as questions.
6. **Compare.** Press `x` to pin up to three companies, then `c`. Glint says so when they aren't
   comparable, for example when they're in different sectors, or one files as a foreign issuer
   whose currency and accounting standard may differ.
7. **Look up any metric.** Every metric name links to the **metric dictionary**: what it tells you,
   the exact formula, and when it misleads.
8. **Export.** Download the results as CSV.

### The 12 presets

| Preset | What it looks for |
|---|---|
| Quality compounders | High returns on capital, fat margins, steady growth and little debt |
| Quality at a reasonable price | Good returns on capital, a decent free-cash-flow yield, top-quartile sector margins |
| Magic Formula | High return on capital and a high earnings yield, ranked together |
| Piotroski value | Cheap on price to book, with a strong 9-point financial-health score |
| Graham net-nets | Priced at two-thirds or less of net current asset value |
| Cash-rich small caps | Cash worth 30%+ of market cap, with positive free cash flow |
| Dividend durability | A 3%+ yield covered by free cash flow, moderate debt, no cut in five years |
| Shareholder yield | 12%+ of market cap returned a year through dividends and buybacks |
| Margin inflection | Operating margin up 20+ percentage points in a year while revenue grew |
| Rule of 40 (software) | Technology companies with revenue growth plus FCF margin of at least 40% |
| Accruals risk (red flags) | Earnings running well ahead of operating cash flow |
| Dilution watch (red flags) | Share count up 10%+ in a year, or stock pay at 15%+ of revenue |

The red-flag presets are risk checks, not buy lists.

## How it works

```
SEC EDGAR bulk files ──► ingest ──► normalize ──► metrics ──► build (DuckDB) ──► API ──► web UI
(XBRL facts, filings)               FY / quarter / TTM   71 metrics,          (FastAPI)  (Next.js)
                                    series, per company  flags, sector ranks
End-of-day prices ──► ingest ─────────────────────────────┘
```

- **Engine** (`engine/`, Python 3.12 with uv, DuckDB and polars):
  - downloads the SEC's bulk XBRL files;
  - builds annual, quarterly and trailing-twelve-month (TTM) series for each company. SEC
    filings never report a fourth quarter on its own, so Glint derives it as the full year minus
    the first nine months;
  - computes 71 metrics with null reasons, applies sector rules and raises flags;
  - writes a versioned build that is swapped in atomically, so a failed refresh never replaces
    a good build.
- **Screen engine:** a JSON screen language compiled to DuckDB SQL, with the sieve, near misses,
  ranking and sector percentiles.
- **API** (`engine/glint/api/`, FastAPI): read-only over the current build, with typed contracts.
  The OpenAPI file and the generated TypeScript types are checked in CI.
- **Web** (`web/`, Next.js and TypeScript): the screener, company pages, comparison, presets and
  the metric dictionary. It's keyboard-first and works on phones.
- **Configuration** (`config/`): the metric registry, the XBRL concept mappings, sectors,
  thresholds and presets. No threshold is written in code.

More detail is in the [methodology](docs/methodology.md), the [metric dictionary](docs/metrics.md)
and the [worked examples](docs/metric-examples.md).

## How it's verified

- **Golden values:** 70 values checked by hand against filings, across 18 companies; the tests
  compare each one at 0.5% tolerance. They cover different sectors, fiscal-year ends, a bank, a
  REIT, a loss-maker and a foreign IFRS filer (TSMC).
- **Spot-checks:** 20 metric values recomputed by hand from their inputs, all agreeing with Glint.
- **Tests:** about 1,400 engine tests, 354 web unit tests and 82 Playwright end-to-end tests, all
  run in CI. The tests use real trimmed SEC filings and a synthetic build, and never touch the
  network.
- **Release checks:** on the release build, every one of 309,816 missing values carries a reason
  code, and a screen with 10 filters answers in 69 ms at the 95th percentile (the budget is
  300 ms).

The [release notes](docs/release-notes.md) give every v0.1.0 success criterion with its evidence,
and the [known limits](docs/known-limits.md) list what Glint gets wrong or leaves out.

## Run it on real data

Real data needs [uv](https://docs.astral.sh/uv/), Node.js 22+, about 8 GB of free disk and about
two hours for the first run, mostly downloading. The SEC requires a contact address in every
request, so you set one in `.env`.

```bash
cp .env.example .env            # set GLINT_SEC_USER_AGENT to "<your name> <your email>"
                                # optional: MASSIVE_API_KEY for prices (free plan works)
make setup                      # Python and Node dependencies
cd engine
uv run glint ingest sec         # SEC bulk files (~3 GB download, ~6 GB extracted)
uv run glint ingest prices --backfill 300
                                # 300 trading days of end-of-day prices; ~1 hour on the free
                                # Massive plan (5 calls a minute)
uv run glint refresh            # build: financials, metrics, flags, then swap it in (~10 min)
uv run glint smoke              # checks every preset and known companies; exit 1 on failure
cd ..
make dev                        # API on :8000 and UI on :3000; one Ctrl-C stops both
```

Without a Massive key, Glint fetches prices from Yahoo Finance's public chart endpoint instead,
and labels them as fallback prices. After the first run, `uv run glint refresh` downloads only
what changed, then rebuilds.

| Command | What it does |
|---|---|
| `uv run glint screen quality-compounders` | Run a preset in the terminal (`--explain` prints the SQL) |
| `uv run glint metrics MSFT --explain roic` | One metric: formula, every input with its tag, period and filing |
| `uv run glint financials AAPL --basis ttm` | A company's normalized series |
| `uv run glint audit` | Outliers and null rates to review |
| `uv run glint universe --summary` | Universe counts by exchange, sector and kind |

Run `glint` commands from `engine/` with `uv run`. If your editor has activated another
project's virtual environment, run `unset VIRTUAL_ENV` first.

## Development

```bash
make check                      # lint, type checks and tests (engine and web)
make e2e                        # Playwright against mock mode (run `npx playwright install chromium` once)
make contracts                  # regenerate the OpenAPI file, JSON Schema and TypeScript types
```

- **Project conventions:** [`CLAUDE.md`](CLAUDE.md).
- **Full spec:** [`docs/SPEC.md`](docs/SPEC.md).
- **Decision logs:** every non-obvious choice is dated, with its reason, in
  [`docs/decisions/`](docs/decisions/).

This repository is a clean snapshot of v0.1.0. Glint was built in a private development repository,
so the pull-request numbers in the docs (for example #75) refer to that history.

### Keyboard

Press `?` in the app for the same list.

| Key | What it does |
|---|---|
| `/` or `⌘ K` | Search companies, presets, filters and actions |
| `f` | Add a filter |
| `j` / `k` | Next / previous result |
| `Enter` | Open the quick view for the focused row |
| `o` | Open the full company page |
| `x` | Pin or unpin a company for comparison (up to 3) |
| `c` | Compare the pinned companies |
| `Esc` | Close the open panel |

## Layout

| Path | What's there |
|---|---|
| `engine/` | Python package `glint`: ingest, financials, metrics, screen engine, API, CLI |
| `web/` | Next.js UI |
| `config/` | Metric registry, XBRL concepts, sectors, thresholds, presets |
| `contracts/` | Generated OpenAPI and screen JSON Schema |
| `docs/` | Spec, methodology, metric dictionary, release notes, known limits, decision logs |

---

*Glint is an educational tool. It is not investment advice, and nothing in it is a
recommendation to buy or sell a security.*
