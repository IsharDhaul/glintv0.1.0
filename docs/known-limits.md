# Known limits (v0.1)

What Glint doesn't do, or does only partly, and why. Each line names where the decision is
recorded. Numbers marked ⟨build⟩ are filled from the release build in `docs/release-notes.md`;
nothing here is an estimate.

## Coverage

- **Enterprise value and other debt-based metrics are null for many companies** (EV, net debt,
  net debt/EBITDA, D/E, ROIC, EV multiples). Most nulls are MISSING_INPUT on total debt:
  the filer's debt isn't tagged in a way Glint can add up without guessing. Share of domestic
  non-financials with EV: 57.3% on the release build (EV null 42.7%, n = 3,415; 48.0% null on 2026-10-31). Causes and counts: WT-03.md (2026-11-03 EV-null breakdown).
  - **Debt reported only as components** (notes, convertibles, credit lines) with no total isn't
    summed, because components often overlap (WT-03.md 2026-10-29).
  - **Debt a 10-Q carries only as custom or dimensional facts** (companyfacts drops them) is
    not read from the filing's own XBRL: a safe rule would fix 5 of 1,363 companies
    (WT-01.md 2026-11-22; user decision).
  - **No zero debt from absence.** A company that never tagged debt is not called debt-free;
    only an exact balance-sheet sum proves a zero (WT-03.md 2026-11-03, #49; WT-06.md 2026-11-22).
- **Interest coverage** is n/m for banks, insurance and capital markets, and MISSING_INPUT where
  interest is tagged only as operating interest, net interest or cash paid (WT-03.md, WT-06.md
  2026-11-22).
- **Utilities, energy and health care** have no company in the golden set (no trimmed fixture);
  their numbers are covered by the pipeline and audit, not by hand-verified values (WT-11.md).

## Outliers the audit shows on the release build (`glint audit`, release build 20261124T170400Z; the same companies as on 20261123T210447Z)

Each class is real data, kept as filed and flagged or listed by the audit; none is filled in.

- **Gross margin far outside 0–100% on tiny revenue** (IFRX: $29K revenue, −$7.2M gross loss;
  SPCE, FFAI): the arithmetic of what was filed.
- **Gross profit larger than revenue** (HCTI: $1,240M gross profit on $31M revenue; JLHL): the
  filer's own tags disagree with each other; the margin shows above 100%, and the audit's
  `gross_margin_range` rule lists them. Not corrected: Glint can't tell which tag is wrong.
- **Equity and share-count jumps of 1,000× or more** (CMDB, XXI, HCAC, BIII, ALLR, BMNR…): new
  entities, SPAC shells and reverse-splitters whose year-ago figures are a predecessor's or a
  shell's; share-count comparisons adjust only for filing-confirmed splits (below).
- **Crypto-treasury companies classed as Banks** by SIC (XXI, BMNR).

## Definitions that leave things out (stated in each metric's definition)

- **Operating leases, pensions and other debt-like items** are not debt.
- **Finance leases count only on the filing's word.** They're added to total debt where the
  latest 10-Q (else 10-K) presents them outside debt; where no filing says which line holds
  them, they're left out and the cell's ⓘ says so (`INPUT_EXCLUDES`) (WT-03.md, WT-06.md
  2026-11-22).
- **Financing obligations** (e.g. sale-leasebacks presented with leases) are not added.
- **IFRS bonds are added to debt only where the filing makes them a separate line** (v1; WT-03.md
  2026-11-24, #88). Non-current bonds and notes are used where `LongtermBorrowings` isn't tagged,
  and summed with it only per company from the balance sheet (TSMC so far). Adding them for
  every filer would double count, because many include the bonds in borrowings. For the 58 other
  default-universe IFRS filers that tagged bonds or notes since 2025, debt may be understated;
  each needs its own balance-sheet check:
  - **Borrowings and bonds the same figure** (the same line tagged twice; nothing missing): WPP,
    RTO, WIT, OTLY.
  - **Borrowings larger than bonds, inclusion not settled** (plainly included for NVO, NGG and
    TLX): NVO, NGG, ASX, TX, AGRO, PBA, KEN, BIOX, RNW, TLX.
  - **Bonds larger than borrowings** (separate lines, so debt is understated): NMG, HITI.
  - **Only an all-bonds total (`BondsIssued` / `NotesAndDebenturesIssued`, usually a breakdown of
    borrowings in the debt note) or only current notes:** DEO, NWG, SNN, RIO, TIGO, GDXU, ICL, SAP,
    PDS, SMFG, DNN, SLF, GGAL, EQNR, LYG, BBD, NAK, BTE, USAS, BTI, TAK, BIPI, BSBR, EVGN, CMBT,
    SPRC, VBNK, NXE, FNUC, VMAR, ELVA, GRAB, QUCY, LCFY, ALVO, HLN, LZM, COOT, TURB, ISOU, KYIV,
    BGSI. Where borrowings are tagged (DEO, RIO, SAP, EQNR, BTI, TAK, HLN…) they likely already
    include the bonds; where none are (NAK, TURB, SPRC, NXE, QUCY, LCFY and the banks), the
    debt is missing.
  - IFRS current bonds and notes are not read on their own: short-term borrowings often already
    include them.
  - IFRS short-term investments count the amortised-cost and FVOCI lines only per company
    (TSMC); for banks the amortised-cost line is loans.
- **Cash can include restricted cash, with no note saying so** (v1; WT-11.md 2026-11-24, user
  decision). Where a filer tags only `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`
  (604 default-universe companies on the release build, SBUX among them), that is Glint's cash,
  so net debt, EV and cash/market cap count restricted cash. `concepts.yaml` marks the tag
  "flag it", but no cell note is shown yet.
- **EPS growth does not subtract preferred dividends** (no preferred-dividend line item yet;
  WT-06.md 2026-10-30).
- **Cost of revenue excluding D&A** is used as a last resort, so those filers' gross margin reads
  higher than peers' (WT-03.md 2026-10-29; noted on the cell).

## Foreign filers and currencies

- **Price metrics are n/m (FOREIGN_PRICE_BASIS) for every 20-F filer and non-USD 40-F filer**
  until FX and ADR ratios exist (F20). 40-F filers reporting in USD are priced (WT-06.md
  2026-10-30). Ratios of two reporting-currency amounts (margins, growth, returns) are kept.
- **ADR ratio changes** appear in the price provider's split table as splits; they aren't share
  splits, and telling them apart needs ADS data Glint doesn't have (WT-02.md 2026-11-03).

## Shares and splits

- **Diluted-share comparisons adjust only for splits the filings confirm** (a later filing
  restated a count by the ratio); unconfirmed splits are left as reported (WT-06.md 2026-11-03).
- **Multi-class companies and Up-Cs**: market cap counts the classes the filings show (cover-page
  classes, filing-confirmed unlisted classes, Up-C units); companies outside those rules use the
  listed class and appear on `glint universe --up-c-candidates` for review (WT-01.md).
- **Share counts some filings leave off the cover** (WT-01.md 2026-11-24, #83; recorded, not
  changed):
  - **RANI**: its cover leaves out 1.1M unpaired units and 83.6M pre-funded warrants that the
    filing counts in basic EPS. Glint uses its diluted count (199.0M; economic count about 224M).
  - **ESRT, NMRK, TAP**: exchangeable units and shares (OP units, Newmark Holdings units, Molson
    Coors Canada exchangeable shares) aren't on the cover. Glint's diluted count already
    includes them.
  - **FCNCA**: Class B trades OTC as FCNCB, which has no price bars. It's counted at the FCNCA
    close.
  - **PARA (Parabolic Technologies)**: the cover doesn't name its 14,983-share Class B, so Glint
    keeps the balance-sheet count (454,398 at 09-30) rather than the cover's 68.0M Class A.
  - **RPC**: its Ex 4.1 says both that Class B dividends are equivalent and that Class B gets
    none. Left for a person.
  - **ZEO**: its count (13.3M) is far below its 46.5M Class A.
- **Primary ticker on a non-equity listing.** Glint prices a company at its most liquid SEC
  ticker. Strive (ASST, at its SATS preferred) and Great Elm (GEG, at its GEGGL notes) are fixed
  by hand (`config/share_classes.yaml` `non_common_symbols`; #84: $7.76B → $1.31B; #87: $765M →
  $64M). CHS and NRUC (no common listing) are still affected. Detecting
  these symbols from the cover needs a new companies.parquet column, a contract change (v1;
  WT-01.md, WT-06.md 2026-11-24).
- **Cover symbols on the exchange axis** (NC, RPC, TAP tag `dei:TradingSymbol` there) aren't
  read from the filing; `cover_symbols` stands in for them, and reading that axis would mean
  re-fetching every cover (WT-01.md 2026-11-24).
- **Share-count change has no freshness limit** (v1; WT-06.md 2026-11-24, #85).
  `share_count_change_yoy` uses the latest diluted count however old it is: about 170 companies
  use a count more than a year older than their TTM end (REG's is from 2020).

## Periods (v1; WT-06.md 2026-11-24, #85)

- **16-week quarters** (ACI, AZO, COST, KR, PEP) fall outside the 80–100-day quarter, so those
  quarters aren't used.
- **The latest 10-K's facts are missing** from SEC's companyfacts for CLX, SENEA, NCL and BTBD.
  Glint shows the latest period it has.
- **Fiscal-year-change detection misses AEHR and FDX**, so neither gets the `fy_change` flag.

## Universe and classification

- **SIC 7389 ("Business Services, NEC") maps to Industrials**, so e.g. MercadoLibre shows as
  Industrials; per-company fixes go in `config/sector_overrides.yaml` (WT-09.md, deferred).
- **Some crypto and commodity ETFs/trusts that file 10-Ks are `kind: operating`** rather than
  funds (WT-01.md 2026-11-03). Still open on build 20261122T225909Z: all 12 examples named
  there (VBNB, SOLC, LTCC, GDOG, TDOG…) are `operating`, and 122 SIC 6221 (commodity contracts)
  filers are `operating` (1 is `no_common_equity`); their SIC still needs checking one by one.
- **SPACs with a SIC other than 6770 are classed `operating`** (found by #81; WT-01.md
  2026-11-24).

## Prices

- **End-of-day only, never today** (free Massive plan, 5 calls/min). Without a key, prices come
  from an unofficial Yahoo endpoint, labelled as a fallback (WT-02.md).

## Not in v0.1

- **No point-in-time history or backtests** (WT-14). Saved screens, natural-language screens
  and scheduled deploys are Wave 4 (WT-12, WT-13, WT-15).

## Interface

- **Mock-mode CSV export** starts at `ticker`, while the API's export of a ranked screen leads
  with `rank` (WT-09.md, deferred).

## Found in the v0.1 review, deferred to v1 (WT-11.md 2026-11-23; user decision)

- **The accounting standard isn't shown.** IFRS filers (e.g. Canadian 40-F filers reporting in
  USD, which get every metric) rank next to US-GAAP filers with no marker in the results or the
  drawer; only the methodology page says so (principle 7).
- **The UI shows Glint's line items, not the XBRL tags behind a value.** The tag, period and
  accession for each number are in `glint metrics TICKER --explain ID` (and `glint financials
  --sources`), not in the API or the drawer (principle 2).
- **Universe defaults are in code** (the $1M average dollar volume floor and the excluded kinds,
  `contracts/screen.py`, mirrored in `web/src/lib/screen/defaults.ts`), not in `thresholds.yaml`.
- **"Excluded" is a total.** The screener shows one count, not a split by reason; the refresh
  report's default-universe count leaves out the dollar-volume and stale defaults.
- **"Every null has a reason" is enforced by tests** (fixture build, smoke), not by a check that
  fails a real build.
- **Some preset wording reads as a verdict** ("red flags" in two preset names, "Good businesses at
  cheap prices").
- **Shift-click secondary sort: the API supports `sort.then` (#80), the UI isn't wired to it yet.**

