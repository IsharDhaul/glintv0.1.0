# Glint

Fundamentals-first US stock screener. Python engine (uv, DuckDB, polars, FastAPI) + Next.js UI.
Full spec: docs/SPEC.md · Worktree rules: docs/worktrees/README.md · Status: docs/STATUS.md

## Principles (never break)
1. **If a number matters, it comes from the source document.** SEC XBRL filings are tier 1. Market prices are a labelled tier 2. AI never supplies numbers.
2. **State your definition.** Every metric carries its formula, inputs (XBRL tags), period basis (TTM/FY/MRQ) and unit. The UI shows them.
3. **Never fabricate.** A missing value is `null` with a **reason code**: "—" in the UI means *missing*, "n/m" means *not meaningful*. No estimates, no fills, no silent zeros.
4. **Compute it yourself.** Glint never imports vendor-computed ratios.
5. **Questions, not verdicts.** Flags are phrased as questions with the evidence attached.
6. **Universe honesty.** Glint always shows what's excluded and why. It never implies the screen covers companies it doesn't.
7. **Comparability before cleverness.** If two companies' numbers aren't comparable (sector, currency, accounting standard), Glint says so instead of ranking them side by side.
8. **Thresholds live in config, never in code.** That covers `config/thresholds.yaml`, `config/metrics.yaml` and `config/presets/`.
9. **Never lose user data.** Pipeline rebuilds can't touch saved screens or watchlists, which live in a separate database file.
Educational tool. Not investment advice.

## Commands
| Command | What it does | Status |
|---|---|---|
| make setup | uv sync + npm ci | live |
| make check | lint + typecheck + tests (engine + web) | live |
| make contracts | regenerate OpenAPI, JSON Schema, TS types | live |
| make test | tests only (engine + web) | live |
| make perf | timing budgets (`perf` marker; CI runs them, `make check` doesn't) | live |
| make e2e | Playwright against mock mode (`npx playwright install chromium` once) | live |
| make docs | regenerate docs/metrics.md | live |
| make dev-api | API with reload on `${GLINT_API_PORT:-8000}` | live |
| make dev-web | UI on `${PORT:-3000}` (`NEXT_PUBLIC_GLINT_MOCK=1` for mock mode) | live |
| make fixtures | = glint fixtures sec (network; needs GLINT_SEC_USER_AGENT in .env) | live |
| make synthetic | = glint fixtures synthetic | live |
| make dev | API + web together (ports from env, then .env; one Ctrl-C stops both) | live |
| glint fixtures sec | real trimmed SEC fixtures for Appendix D → engine/tests/fixtures/sec | live |
| glint fixtures synthetic [--n 6000] [--seed 7] | synthetic build + data/current.json + web/mocks | live |
| glint ingest sec [--no-download] [--force-extract] [--covers-only] | download + extract SEC bulk files, fetch cover-page share classes of new 10-K/10-Qs (raw/sec-covers), build companies.parquet; --covers-only: just the covers | live |
| glint universe --summary / glint universe TICKER / --up-c-candidates | universe counts / one company / multi-class covers the Up-C logic leaves alone (review list) | live |
| glint ingest prices [--backfill N] | daily bars | (planned WT-02) |
| glint price TICKER | bars + price stats | (planned WT-02) |
| glint financials TICKER [--basis fy\|q\|ttm\|mrq] [--periods N] [--sources] / --coverage [--write DB] [--facts-dir DIR] | normalized series / universe coverage | live |
| glint screen PRESET-OR-FILE [--synthetic] [--explain] [--show N] | run a screen in the terminal (funnel, results, near misses; --explain prints SQL + params) | live |
| glint metrics TICKER [--category c] [--explain id] [--db PATH] | metrics from a build, by category; --explain: formula, inputs (value, period, tag, accession), result | live |
| glint audit [--db PATH] [--top N] [--extremes N] | §4.6 rules, per-metric distributions, P0 null rates (default universe) | live |
| glint refresh [--no-download] [--skip-prices] [--only/--from STAGE] [--dry-run] | full pipeline, build-then-swap; report in data/reports/<build_id>.md | live |
| make schedule-install / schedule-remove | optional launchd job: glint refresh at 09:15 London | live |
| glint serve [--port] [--no-reload] | API (uvicorn, reload on) on `GLINT_API_PORT` | live |
| glint smoke [--expectations FILE] | presets, Appendix D lookups, search cases on the current build; exit 1 on failure | live |

## Conventions
- Percentages are fractions everywhere (0.15). pp stored as fractions. Multiples are x.
- One gateway per source: SEC → core/http.py; prices → PriceProvider. No other network calls.
- Pure core (periods, metrics, DSL, ranking) with unit tests; I/O at the edges.
- Tests: real trimmed fixtures + synthetic build; never network, never real data dirs.
- Generated files (contracts/*.json, web/src/lib/api/types.ts, docs/metrics.md) are never hand-edited.
- Each worktree edits only the paths it owns (docs/worktrees/README.md §8.4).
- Decisions: one dated line in docs/decisions/WT-NN.md for every non-obvious choice.
- Never merge a PR unless `gh pr checks <n>` shows every check passing and `mergeStateStatus` is CLEAN. GitHub branch protection isn't available on this repo, so this rule is the protection.

## Gotchas
- companyfacts fy/fp describe the filing, not the period — use start/end.
- Q4 is never filed: Q4 = FY − 9M YTD.
- Capex/dividends/buybacks are positive outflows in XBRL.
- `Liabilities` often untagged; `LongTermDebt` may include the current portion.
- DuckDB: one writer per file; API is read-only; builds swap via data/current.json.
- Free Massive plan: 5 calls/min, end-of-day, never "today".
- Tests: build Settings with `tests.conftest.make_settings(...)` (ignores env and .env); use the `db_dir` fixture for code that reads global settings.
- Web pins TypeScript 5.x: openapi-typescript and typescript-eslint don't support TS 7 yet.
- SEC: User-Agent with contact required; ≤ 8 req/s; bulk files for the universe.
