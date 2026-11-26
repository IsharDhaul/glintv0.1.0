# WT-02 · prices

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 1 | M | WT-00 | `wt02-prices` | `worktree-wt02-prices` | — |

**Goal.** Daily prices for the whole universe through a swappable provider interface, plus the price-derived stats every price-tier metric needs.

**Owns.** `engine/glint/ingest/prices/`, `engine/tests/prices/`, `docs/decisions/WT-02.md`.

**Must not touch.** Contracts, `cli.py`, other modules.

**Steps**

1. **`PriceProvider` protocol:**
   - `bars_for_date(date) -> list[Bar]` (all tickers)
   - `history(ticker, start, end) -> list[Bar]`
   - `splits(since) -> list[Split]`
   - Errors raise `SourceError`. Every call is cached.
2. **`MassiveProvider`:**
   - Uses the grouped-daily endpoint with split-adjusted bars, and the API key from `.env`.
   - Paces itself with `MASSIVE_CALLS_PER_MIN` (default 5).
   - Treats an empty response on a weekday as a market holiday and records it, so it isn't refetched.
   - Never requests the current day (403 on the free plan).
   - Put the base URL in settings and confirm it against Massive's docs (Polygon.io was renamed Massive on 30 Oct 2025).
3. **`YFinanceProvider` fallback.** Batched history downloads (around 200 tickers per batch, with polite sleeps). It's used when there's no Massive key, and it logs that it's in fallback mode.
4. **Storage:** `GLINT_RAW_DIR/prices/daily/date=YYYY-MM-DD/part.parquet` under `raw.lock`, plus splits in `prices/splits.parquet`.
5. **Backfill** (`glint ingest prices --backfill 300`): resumable, skipping dates already on disk. It shows an ETA (about 51 minutes per 252 sessions at 5 calls a minute) and can be safely killed and restarted.
6. **Symbol mapping:** provider symbol ↔ Glint canonical (`BRK.B`). Write an unmatched report covering universe tickers with no prices and price tickers not in the universe (top 50).
7. **`price_stats`** (pure functions over polars): close, returns 1/3/6/12m, 12–1 momentum, 52-week high and % off it, 1-year volatility, 3-month average dollar volume and `history_days`. If there's too little history for a stat, it's null with `INSUFFICIENT_HISTORY`.
8. **Split check helper:** `split_between(ticker, d1, d2) -> ratio | None`, which WT-06 uses for share-count safety.
9. **CLI:** `glint ingest prices [--date D] [--backfill N]` and `glint price AAPL` (last bars plus stats).
10. **Tests:**
    - Recorded JSON fixtures for 3 grouped-daily dates and one split.
    - Unit tests for every stat (hand-computed tiny series), pacing logic (fake clock) and resume.

**Acceptance criteria**

- [ ] The backfill resumes after being killed, without refetching saved dates (shown in the logs).
- [ ] ≥ 95% of NYSE/Nasdaq universe tickers have a price on the latest date. The real % and the unmatched list are recorded.
- [ ] With `MASSIVE_API_KEY` empty, the fallback works for the Appendix D tickers and says so.
- [ ] Stats are correct on the hand-computed fixtures (exact to 1e-9).
- [ ] You eyeball `glint price AAPL`'s 52-week high against any public chart and note the date checked.
- [ ] No network in tests.

**Demo commands:** `glint ingest prices --backfill 30` · `glint price AAPL` · `glint price BRK.B`.

**Decisions to record:** the provider base URL and plan limits as you found them; the real backfill time; how the canonical symbol rules are implemented; holiday handling.

**Gotchas**

- Returns are **price-only** (no dividends). Label them that way.
- Adjusted bars feed returns, but market cap uses the *unadjusted* close × shares, with a split check.
- yfinance is unofficial: keep it behind the interface and never let it block a build.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-02 (prices).
Your brief: docs/worktrees/WT-02-prices.md. Spec context: docs/SPEC.md §4.1, §2.4 (price-tier metrics), §5.7.
All provider access goes through the PriceProvider interface. Free Massive plan = 5 calls/min, end-of-day, never today.
Before coding the Massive client, read Massive's current docs for the grouped-daily endpoint and record the exact URL/params in docs/decisions/WT-02.md.
```
