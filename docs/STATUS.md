# Worktree status

| WT | Name | Wave | Status | PR | Started | Merged | Sessions | Notes |
|----|------|------|--------|----|---------|--------|----------|-------|
| 00 | foundation | 0 | ✅ | #1 | 2026-10-28 | 2026-10-29 | 1 | |
| 01 | sec-ingest | 1 | ✅ | #6 | 2026-10-29 | 2026-10-29 | 2 | TXSE + has_facts contracts (#2, #4); BRK share classes pending (WT-06) |
| 02 | prices | 1 | ✅ | #3 | 2026-10-29 | 2026-10-29 | 1 | yfinance dep removed (chore PR, 2026-11-23); the Yahoo fallback uses the chart endpoint directly |
| 03 | normalize | 1 | ✅ | #12 | 2026-10-29 | 2026-10-30 | 2 | Core coverage 83.6% (domestic non-fin, TTM/MRQ) after review fixes: R1 tripwire, not 90%; §4.3 rule 6 amended (TTM bridge); hand-offs: NVRI predecessor (WT-01), EPS TTM + common TTM end (WT-06), debt component tags in whitelist (WT-00) |
| 04 | screen-engine | 1 | ✅ | #10 | 2026-10-29 | 2026-10-29 | 1 | NearMiss.note contract change proposed (decisions/WT-04.md); web/mocks stale since #6 (WT-00/WT-05) |
| 05 | web-ui | 1 | ✅ | #19 | 2026-10-29 | 2026-10-30 | 2 | Mock mode only; contract gaps 1–4 in decisions/WT-05.md for §8.6; web/mocks regenerated; real-API switch is WT-09 |
| 06 | metrics | 2 | ✅ | #22 | 2026-10-30 | 2026-10-30 | 1 | All 71 metrics live; concepts follow-up #23 (NVDA marketable securities, KO notes payable); hand-offs: preferred_dividends CONTRACT (eps), WT-03 share-count scale + revenue-tag mismatches, WT-00 §4.5 vs §4.3 split; BRK share classes to update from the Q3 10-Q |
| 07 | pipeline | 2 | ✅ | #20 | 2026-10-30 | 2026-10-31 | 2 | cold 13.3 min, warm 8.0 min; --no-download 8.2 min (over §4.8 5-min target: financials 7–8 min, hand-off WT-03); kill test live mid-metrics; flags_quality + archive_snapshot folded into WT-06 MetricsStage; pre-merge review: 8 of 10 findings fixed (incl. raw.lock prune race); hand-offs: WT-03 financials speed, WT-06 archive() raw.lock no-wait + swallowed tracebacks |
| 08 | api | 2 | ✅ | #14 | 2026-10-29 | 2026-10-30 | 1 | needed CONTRACT #13 (nullable SourceFiling.form); search real-name cases repeat in WT-09 |
| 09 | integration | 3 | ✅ | #31 | 2026-10-31 | 2026-10-31 | 1 | smoke 36/36 (--perf) on a real build; §5.10 all met on real data (apply-filter after 350 → 250 ms debounce + "Updating…" state; scroll at MAX_LIMIT 1,000 rows, agreed); warm refresh 9.6 min (financials 9.3, WT-03 hand-off); fresh-clone README run passed; review: 7 findings fixed; hand-offs: core settings path resolution (WT-00/§8.6), SEV null-reason precedence (WT-06), WAT share scale + EV/net-debt null rates (WT-03), mock CSV omits rank (web) |
| 10 | presets-methodology | 3 | ✅ | #30 | 2026-10-31 | 2026-11-02 | | 12 presets tuned on real build 20261031T142930Z (before/after in decisions/WT-10.md); methodology page (/about), `tells_you`/`misleads` for all 71 metrics, docs/metric-examples.md; used CONTRACT #28; hand-off: 21 net-nets with impossible market caps (→ #34/#37 market_cap_implausible) |
| 11 | verify-release | 3 | 🟦 | #75 | 2026-11-23 | | | golden 70/70 verified, spot-checks 20/20 agree; coverage 83.8% (< 90%, recorded, user decision); Nexus session deferred to v0.1.1 (user decision 2026-11-26) |
| 12 | saved-screens | 4 | ⬜ | |  | | | |
| 13 | nl-screens | 4 | ⬜ | |  | | | |
| 14 | history-pit | 4 | ⬜ | |  | | | |
| 15 | deploy-schedule | 4 | ⬜ | |  | | | |

## Follow-ups after WT-09

Fix PRs on real-build findings, by owning worktree. ✅ merged.

| PR | Owner | Status | Merged | What |
|----|-------|--------|--------|------|
| #32 | CONTRACT | ✅ | 2026-11-02 | REPO_ROOT guard: refuse to run against another checkout's package |
| #33 | WT-06 | ✅ | 2026-11-02 | null-reason precedence across inputs |
| #34, #37 | CONTRACT, WT-06 | ✅ | 2026-11-03 | `market_cap_implausible` flag |
| #35 | WT-06 | ✅ | 2026-11-03 | NO_INTEREST_EXPENSE only on positive evidence |
| #36 | WT-03 | ✅ | 2026-11-03 | share-count plausibility (zero, placeholder, mis-scaled) |
| #38, #49 | WT-03 | ✅ | 2026-11-03, 2026-11-05 | total_debt from filers' own totals; zero debt only on balance-sheet evidence (EV coverage) |
| #39, #40, #41 | WT-06, WT-03 | ✅ | 2026-11-03 | docs: bug lists, EV-null breakdown |
| #42, #45 | CONTRACT, WT-01 | ✅ | 2026-11-03 | Kind `no_common_equity` for issuers with no listed common stock |
| #43 | WT-06 | ✅ | 2026-11-03 | split-adjust diluted-share comparisons (filing-confirmed splits only) |
| #44, #47 | WT-02 | ✅ | 2026-11-03 | keep every same-day split leg, net on read |
| #46 | WT-01 | ✅ | 2026-11-05 | HUBG and DUOL share-classes entries |
| #48, #50 | CONTRACT, WT-01 | ✅ | 2026-11-05, 2026-11-11 | Up-C detection from cover-page share classes (`is_up_c`, `up_c_evidence`) |
| #51 | WT-03 | ✅ | 2026-11-21 | Up-C market cap counts every cover-page class |
| #53 | WT-03, WT-06 | ✅ | 2026-11-22 | interest_expense maps InterestAndDebtExpense + InterestExpenseBorrowings; interest_coverage n/m for financials; absence-as-zero-debt declined |
| #54 | WT-01 | ✅ | 2026-11-22 | the 14 missed Up-Cs: complement match at 1pp, filing-cited `up_c.confirmed` (13) and `excluded` (DKNG), `glint universe --up-c-candidates` |
| #56 | WT-09 | ✅ | 2026-11-22 | smoke: SEV `fcf_growth_yoy` NEGATIVE_DENOMINATOR (Q3 2026 10-Q added the year-back TTM; prior FCF −17.5M) |
| #58 | WT-01 | ✅ | 2026-11-22 | Up-C review list filtered on Glint's share count (`up_c.candidate_min_ratio`); ZETA's combined cover member; +31 confirmed, +3 excluded Up-C entries |
| #59 | WT-01, WT-06 | ✅ | 2026-11-22 | market cap from separately listed cover-page classes (`listed_classes`, 24 companies: HEI, LEN, FOXA, BRK …); `cover_excluded` (USCI, YSAG, ESBA, SF); BRK hand entry retired, DUOL re-keyed; unlisted-class triage CSV |
| #61 | WT-01 | ✅ | 2026-11-22 | `common_classes` drops a cover member equal to the sum of the others (`up_c.total_member_tolerance`: GCT, KNSA, BLK, USCI); the seven ambiguous Up-Cs: FPH, OPAL confirmed; ANDG, AVAT, MC, SUN excluded; BXBL ordinary dual-class |
| #62 | WT-01, WT-06 | ✅ | 2026-11-22 | filing-confirmed unlisted classes (`unlisted_economic`, 47: GOOGL, UAA, Z, FWONK, CENT, HUBG, DUOL + 40 from the triage CSV) priced at the class they convert into; counts from the cover; hand-keyed counts retired; market_cap definition states the share basis |
| #66 | WT-03 | ✅ | 2026-11-22 | class-only share counts dropped (IHRT: special warrants tagged undimensioned; `shares_class_ratio`); `four_quarters` O(1) (~20% faster stage); financials slowdown was machine load, not #53 |
| #55 | WT-01 | ✅ | 2026-11-22 | cover cache v2: debt facts + ASC 842 lease lines from each instance, latest 10-K fetched too; measurements for the finance-lease rule; 10-Q debt rule dropped |
| #57, #63 | CONTRACT, WT-01 | ✅ | 2026-11-22 | finance-lease presentation from each filing's ASC 842 declaration (`finance_lease_*` columns): 413 stated, 313 not stated |
| #64 | WT-03 | ✅ | 2026-11-22 | finance leases in total_debt where the filing presents them outside debt: 166 companies, EV median +0.25% (KSS +64%) |
| #60, #65 | CONTRACT, WT-06 | ✅ | 2026-11-22 | INPUT_EXCLUDES ⓘ on debt-based values when the filing doesn't place the finance lease (188 companies); definitions |
| #67 | WT-10 | ✅ | 2026-11-23 | `docs/metric-examples.md` regenerated on build 20261122T225909Z (#62 market_cap definition); 71/71 examples |
| #68 | WT-01 | ✅ | 2026-11-23 | Up-C confirms from the filings: MDLN, CNM, TPG (Class B paired 1:1 with exchangeable units); BLK (common + Subco units exchangeable 1:1; not a classic Up-C) and SUN (common + Class D, never Class C) via `classes`; Up-Cs 88 → 93 |
| #70 | WT-01, WT-06 | ✅ | 2026-11-23 | `unlisted_economic` +43 (90): WMG; MA, UHS, LEVI, ECHO, CRCL from #62's rejects via their Description of Securities/charter exhibits; 38 more from the triage CSV; UNF, RBCAA, ATRO, BRC, MCHB, AOS rejected for different economics; GCMG, NMRK for the Up-C owner |
| #71 | WT-03 | ✅ | 2026-11-23 | financials stage 456 → 261 s (median, whole universe), output byte-identical: tuple facts and periods, one dedupe per item, GC paused while loading |
| #72 | WT-01, WT-06 | ✅ | 2026-11-23 | review fixes (principle 8): late-filer / FY-change rules from thresholds.yaml; flag questions built from their thresholds; one stale number |
| #73 | WT-01 | ✅ | 2026-11-23 | GCMG confirmed as an Up-C (Class C paired 1:1 with GCMH Common Units exchangeable one-to-one): market cap $2.585B → $2.559B; Up-Cs 94 |
| #74 | WT-01, WT-06 | ✅ | 2026-11-23 | `unlisted_economic` +44 (134), rows 111–175 of the triage CSV: ADT and FFAI get a market cap; APC +278% (Class B now counted); MCS, HOV, MBIO, AENT rejected for different economics; IIIV, MBUU, FNKO, FOA, VGAS, PRPL, RANI, ESRT for the Up-C owner; RPC, NC need code (no tagged symbol) |
| #77 | WT-06 | ✅ | 2026-11-23 | market-cap split window starts at the count's share basis (cover date, or the filing date for a statement count, SAB Topic 4C): ENHA $8.1M → $81.3M, PARA ×10; no other company |
| #78 | WT-01 | ✅ | 2026-11-23 | Up-C triage from #74: IIIV, FNKO, FOA, VGAS, PRPL confirmed (Class B/C paired 1:1 with exchangeable units; Up-Cs 99); MBUU (12 per-holder voting shares) and ESRT (OP units not on the cover) excluded; RANI left out (pre-funded warrants and unpaired units need code) |
| #81 | WT-01 | ✅ | 2026-11-24 | `--up-c-candidates` ignores warrant/right/preferred/depositary/note symbols (`up_c.non_equity_symbol_words`; VGAS was hidden by VGASW): list 44 → 74; ANNA confirmed (Up-Cs 100); SF, AENT, FBYD, RUM, USDE, ZEO excluded; 13 SPAC-like names untriaged |
| #82 | WT-01, WT-06 | ✅ | 2026-11-24 | `cover_symbols` for covers that tag the symbol only on the exchange axis: NC (Class A at NC; Class B added to `unlisted_economic`), RPC (symbol only; its Class B dividend wording conflicts, left for a person); TAP to `cover_excluded` (Molson Coors Canada exchangeable shares aren't on the cover) |
| #83 | WT-01 | ✅ | 2026-11-24 | decisions line: share-basis items recorded, not changed (RANI, ESRT/NMRK/TAP, FCNCA, PARA, RPC, exchange-axis symbols, primary ticker on a non-equity listing: ASST, GEG) |
| #84 | WT-06 | ✅ | 2026-11-24 | fix: Strive (ASST) priced at its common stock, not the SATS preferred (`non_common_symbols`); $7.76B → $1.31B |
| #87 | WT-06 | ✅ | 2026-11-24 | fix: Great Elm (GEG) priced at its common stock, not the GEGGL notes (`non_common_symbols`); $763.5M → $66.3M |
| #88 | WT-03, WT-06 | ✅ | 2026-11-24 | IFRS bonds as non-current debt fallback; TSMC bonds + current financial assets summed from its 20-F (ROIC 51.3% → 39.1%); FY-history wording for share-count change and ROIC |

Status: ⬜ not started · 🟨 building · 🟦 in review · ✅ merged · ⛔ blocked (say on what)
