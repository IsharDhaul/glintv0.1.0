# WT-01 · sec-ingest

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 1 | M | WT-00 | `wt01-sec-ingest` | `worktree-wt01-sec-ingest` | — |

**Goal.** Download the SEC bulk files reliably. Turn them into `facts_raw` (Parquet, whitelisted tags only) and a `companies` table with tickers, exchanges, sectors, kinds and filing dates.

**Owns.** `engine/glint/ingest/sec/`, `engine/glint/universe/`, `config/sectors.yaml`, `config/sector_overrides.yaml`, `config/share_classes.yaml`, `engine/tests/ingest_sec/`, `engine/tests/universe/`, `docs/decisions/WT-01.md`.

**Reads.** `core/http.py`, `core/filelock.py`, `contracts/*`, `config/concepts.yaml`. **Must not touch:** contracts, `cli.py`, other worktrees' folders.

**Steps**

1. **Downloader** (`glint ingest sec`):
   - Fetch `companyfacts.zip`, `submissions.zip` and `company_tickers_exchange.json` into `GLINT_RAW_DIR/sec/<YYYY-MM-DD>/`, under `raw.lock`.
   - Use conditional GET, so an unchanged file is skipped.
   - Verify zip integrity, and write `manifest.json` (URL, bytes, sha256, last-modified, fetched_at).
   - Keep the last 3 dated folders.
2. **Facts extractor:**
   - Stream each member of `companyfacts.zip` *without extracting to disk*, and parse with orjson.
   - Keep taxonomies `us-gaap`, `ifrs-full` and `dei`, and only tags in `concepts.yaml` plus the dei cover tags.
   - Emit rows in the `facts_raw` schema to Parquet in batches, partitioned by `cik % 64`.
   - Log stats: companies parsed, facts kept, files with no kept facts.
3. **Companies from submissions:**
   - Fields: name, tickers, exchanges, sic, sicDescription, stateOfIncorporation, fiscalYearEnd, category, entityType, and former names.
   - From recent filings: latest 10-K/10-Q/20-F/40-F dates and accession numbers, any `NT 10-K`/`NT 10-Q` in the last 12 months, and fiscal-year-end changes.
4. **Ticker map:**
   - Canonical symbol format uses a dot for classes (`BRK.B`). Keep `sec_symbol` as given.
   - One CIK can have several tickers; store `tickers[]`.
   - Set a provisional `primary_ticker` (the first in the SEC file). WT-06 finalizes it by liquidity.
   - Exclude OTC by default with `exchange` kept, so the universe toggle can include it.
5. **Classification:**
   - `sector` comes from SIC via `sectors.yaml`, with `sector_overrides.yaml` applied.
   - `kind`:
     - `spac` for SIC 6770
     - `fund` for SIC 6722/6726
     - `shell` for an entity type or category that signals one (record your rule)
     - `operating` otherwise
   - `is_foreign_filer` if the latest annual report is a 20-F or 40-F.
   - `taxonomy` is whichever of us-gaap or ifrs-full holds the revenue facts.
   - `reporting_currency` is the most common currency unit on revenue facts.
6. **Investigate multi-class companies.** For GOOGL/GOOG and BRK.A/BRK.B, inspect what dei and us-gaap share facts companyfacts actually contains (per class, or total only?). Write the findings in the decisions file, and seed `share_classes.yaml` if needed (§4.3 rule 11).
7. **Universe summary** (`glint universe --summary`): counts by exchange, sector, kind and foreign/domestic, plus the number of CIKs with no XBRL facts. `glint universe AAPL` shows one company's record.
8. **Tests.**
   - Unit tests for symbol normalization, SIC → sector, kind rules and filing-date extraction (fixtures).
   - An extractor test on a tiny synthetic zip built in the test.
   - One `@pytest.mark.live` test for the downloader.

**Acceptance criteria**

- [ ] `glint ingest sec` completes. A second run the same day is a no-op (logged as unchanged).
- [ ] `facts_raw` has rows for every Appendix D company. Spot check: AAPL has revenue facts under at least one Appendix B revenue tag.
- [ ] `glint universe --summary` prints real counts, and the counts are recorded in `docs/decisions/WT-01.md`.
- [ ] GOOG and GOOGL map to one CIK, and BRK.A and BRK.B map to one CIK.
- [ ] Each Appendix D ticker gets its expected sector (table-driven test).
- [ ] Extraction peak memory is < 2 GB (`/usr/bin/time -l` on macOS), and the wall time is recorded.
- [ ] The multi-class investigation (step 6) is written up.
- [ ] No network in non-live tests.

**Demo commands:** `glint ingest sec` · `glint universe --summary` · `glint universe BRK.B` · `glint universe TSM`.

**Decisions to record:** real file sizes and times; universe counts; the shell-detection rule; multi-class findings; any SIC mapping changes.

**Gotchas**

- `fy`/`fp` in facts describe the filing. Leave them raw; WT-03 handles periods.
- `company_tickers_exchange.json` includes OTC and some non-operating entities.
- Some CIKs have tickers but no XBRL facts (funds, very new registrants). Keep them in `companies` with `has_facts=false`.
- Don't call per-company APIs for the universe: bulk only. The 10 req/s ceiling applies to everything.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-01 (sec-ingest).
Your brief: docs/worktrees/WT-01-sec-ingest.md. Spec context: docs/SPEC.md §2.3, §4.1–4.4, §4.7.
Bulk files only — never per-company SEC calls for the universe. Stream the zip; don't extract it to disk.
Step 6 (multi-class investigation) is research: write findings to docs/decisions/WT-01.md before coding share-class logic.
```
