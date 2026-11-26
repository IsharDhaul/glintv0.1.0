# WT-03 · normalize ★

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 1 | L | WT-00 (step 9 needs WT-01) | `wt03-normalize` | `worktree-wt03-normalize` | — |

**Goal.** Turn raw XBRL facts into trustworthy, comparable financial series for every company: FY, discrete quarters, TTM and instants per line item, each value carrying its source tag and filing. **This is the hardest and most important worktree.** Take it slowly.

**Owns.** `engine/glint/financials/`, `config/concepts.yaml`, `engine/tests/financials/`, `docs/decisions/WT-03.md`.

**Must not touch.** Contracts (use the §8.6 protocol if `LineItem` needs a new member), `cli.py`, ingest code.

**Steps**

1. **Concept map loader.** Load `concepts.yaml` into typed structures: line item → kind (duration/instant) → ordered tags per taxonomy → expected unit kind → sign note → derivation rule. Validate it against the `LineItem` enum.
2. **Period engine** (pure):
   - Classify each fact by duration length (§4.3 rule 2).
   - Key periods by `(start, end)`, never by `fy`/`fp`.
   - Write a unit test for the "10-K comparatives tagged with the filing's `fy`" case, using a real fixture.
3. **Dedupe and precedence:**
   - For each (line item, period): pick the highest-priority tag with a value.
   - Within a tag, keep the latest-`filed` value as `value`, and the earliest as `first_filed_value`/`first_filed_date`.
   - Record `source_tag` and `source_accn`.
4. **Discrete quarters** (§4.3 rule 5), including derived Q2/Q3/Q4 with `derived=true`.
5. **TTM** (§4.3 rule 6): contiguous quarters only, with the FY consistency check logged as a warning when it fails.
6. **Instants, averages and history:**
   - The MRQ instant per line item.
   - The instant nearest to one year earlier (±45 days) for averages.
   - FY series (last 10) and TTM series (last 12 quarter-ends).
7. **Derived items** (§4.3 rule 9): gross_profit, total_liabilities, total_debt (no double count), ebitda, fcf. Each is flagged.
8. **Units, currency and shares:**
   - Reject unit mismatches.
   - Set `reporting_currency` per company.
   - Apply the share-count priority (§4.3 rule 11) and record `shares_as_of`.
   - Detect fiscal-year changes (rule 14) so no TTM straddles one.
9. **Write and report** (after WT-01 merges, rebase first):
   - Write the `financials` table for the whole universe from `facts_raw`.
   - `glint financials --coverage` prints the % of universe companies with each line item, at latest TTM/MRQ, split into domestic non-financials, financials and foreign.
   - Iterate on `concepts.yaml` until core coverage is ≥ 90% for domestic non-financials, or until gains are below 1 pp per pass (R1 tripwire). Record the final numbers.
10. **CLI.** `glint financials AAPL [--basis fy|q|ttm|mrq] [--periods 8] [--sources]` prints a table with periods as columns. `--sources` shows the tag and accession per cell.

**Acceptance criteria**

- [ ] For every Appendix D company, core items for the latest FY are present, or there's a reason logged (for example JPM gross profit: n/a by design).
- [ ] For AAPL, MSFT, KO and NVDA, the TTM at the last fiscal year end equals the FY value within 0.5%, and the sum of 4 discrete quarters equals TTM exactly.
- [ ] NVDA (52/53-week year), MSFT (June FY) and AAPL (September FY) get correct period labels and ends.
- [ ] TSM is built from `ifrs-full` tags in its reporting currency, with currency recorded.
- [ ] The comparatives test proves `fy`/`fp` isn't used to identify periods.
- [ ] You check 2 values per company for AAPL, KO and NVDA against the 10-K (revenue, CFO). They're entered in `engine/tests/golden/golden_values.csv` with accession and location.
- [ ] Coverage report numbers are recorded (step 9).
- [ ] All period logic has unit tests, and coverage of `financials/` is ≥ 90% (`pytest --cov`).

**Demo commands:** `glint financials AAPL --basis ttm --periods 8 --sources` · `glint financials JPM --basis fy` · `glint financials TSM --basis fy` · `glint financials --coverage`.

**Decisions to record:** every tag added to or reordered in `concepts.yaml` (with the company that needed it); duration bounds you changed; the total_debt rule as implemented; coverage numbers per pass.

**Gotchas**

- The same number appears in many filings. Dedupe by period, not by accession.
- Q4 is never filed. YTD facts are how you get Q2, Q3 and Q4.
- Capex, dividends and buybacks are positive numbers representing outflows.
- `Liabilities` is often missing, so derive it. `LongTermDebt` often includes the current portion.
- Banks have no gross profit or current assets. That's a null with a reason, not a bug to fix.
- Don't "fix" weird values by hand in code. Use a config entry with a reason, or leave a null with a note.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-03 (normalize).
Your brief: docs/worktrees/WT-03-normalize.md. Spec context: docs/SPEC.md §4.3 (read every rule twice), §4.6, §4.7, Appendix B.
Work from committed fixtures in engine/tests/fixtures/sec/ for steps 1–8; step 9 waits until WT-01 is merged (rebase first).
Periods are identified by start/end dates only. Never sum alternative tags. Every derived value is flagged.
If a value looks wrong, show me the raw facts behind it before changing any rule.
```
