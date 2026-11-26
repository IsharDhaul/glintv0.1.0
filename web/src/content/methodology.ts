// Methodology copy for /about (WT-10). The same text lives in docs/methodology.md; methodology.test.ts
// checks the two have the same section headings and that the config values quoted here match config.
// Inline markup: **bold**, `code`, [text](/path). page.tsx renders it and holds no copy of its own.

export type Block =
  | { kind: "p"; text: string }
  | { kind: "ul"; lead?: string; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][]; foot?: string };

export interface MethodologySection {
  id: string;
  title: string;
  blocks: Block[];
}

export const INTRO =
  "How Glint gets its numbers, what it leaves out, and where its numbers can mislead.";

/** Manual sector overrides from config/sector_overrides.yaml (each with its reason). A test keeps this in step. */
export const SECTOR_OVERRIDES: {
  ticker: string;
  sector?: string;
  kind?: string;
  reason: string;
}[] = [
  {
    ticker: "QVCG",
    kind: "operating",
    reason:
      "Temporary, review by 2026-11-30: QVC, Inc. (wholly owned) became the listed QVC Group, Inc. on 2026-08-04, and its latest 10-Q still reports 1 share and no EPS, which would otherwise mark it as having no listed common stock.",
  },
  {
    ticker: "MELI",
    sector: "Consumer Discretionary",
    reason:
      "Registered under SIC 7389 (business services, a catch-all), but the 10-K calls it \"the leading online commerce and fintech ecosystem in Latin America\" (10-K for FY2025). Online retail sits in Consumer Discretionary.",
  },
  {
    ticker: "NUTX",
    sector: "Health Care",
    reason:
      "Registered under SIC 7389 (business services, a catch-all), but operates 26 hospital facilities, including micro-hospitals and specialty hospitals, plus physician networks (10-K for FY2025). Hospitals sit in Health Care.",
  },
  {
    ticker: "EBAY",
    sector: "Consumer Discretionary",
    reason:
      "Registered under SIC 7389 (business services, a catch-all), but the 10-K calls it \"a global commerce leader and third-party marketplace\" (10-K for FY2025). Online retail sits in Consumer Discretionary.",
  },
  {
    ticker: "ETSY",
    sector: "Consumer Discretionary",
    reason:
      "Registered under SIC 7389 (business services, a catch-all), but it operates \"two-sided online marketplaces that connect millions of creative entrepreneurs with buyers around the world\" (10-K for FY2025). Online retail sits in Consumer Discretionary.",
  },
  {
    ticker: "PYPL",
    sector: "Technology",
    reason:
      "Registered under SIC 7389 (business services, a catch-all), but its \"products are designed to enable digital payments\" (10-K for FY2025). Digital payments platforms sit in Technology.",
  },
];

export const METHODOLOGY: MethodologySection[] = [
  {
    id: "data-sources-and-tiers",
    title: "Data sources and tiers",
    blocks: [
      {
        kind: "ul",
        items: [
          "**Tier 1: SEC EDGAR filings.** Every fundamental number comes from the XBRL facts companies file with the SEC (10-K, 10-Q, 20-F, 40-F). Glint reads the SEC's nightly bulk files and the SEC's ticker-to-exchange list.",
          "**Tier 2: market prices.** Daily end-of-day closes from a price provider, never intraday. Every number that uses a price (market cap, P/E, yields, EV multiples) is labelled with its price date.",
          "A price number never overwrites a filing number. If prices are missing, price-based metrics are missing (—). A company with no price history also has no trading volume, so the default liquidity floor leaves it out of the universe. Turn the floor off to screen it on fundamentals alone.",
          "Glint computes every ratio itself from those inputs. It never imports a ratio someone else computed, and AI never supplies a number.",
          "Every page shows the date of the SEC bulk file, the price date and the build id.",
        ],
      },
    ],
  },
  {
    id: "universe-rules",
    title: "Universe rules",
    blocks: [
      {
        kind: "p",
        text: "The default universe is every company (one row per SEC CIK, so a company with two tickers appears once) with a ticker on NYSE, Nasdaq, NYSE American or the Texas Stock Exchange.",
      },
      {
        kind: "ul",
        lead: "**Left out by default** (each is a toggle):",
        items: [
          "SPACs and blank checks (SIC 6770)",
          "Funds and trusts (SIC 6722, 6726)",
          "Shell companies (set by hand: the bulk data has no shell flag)",
          "Issuers with no listed common stock: every ticker is a debt or preferred security (bonds, notes, preferreds)",
          "OTC listings",
          "Companies with no XBRL financial facts",
          "Companies below the average daily dollar volume floor (default $1M over the last 3 months)",
          "Companies whose latest annual report is more than 15 months old. Turn the toggle on to include them, marked **STALE**.",
        ],
      },
      {
        kind: "ul",
        lead: "**Included but labelled:**",
        items: [
          "Banks, insurers and capital-markets firms, with sector rules for metrics that don't apply to them (see the applicability matrix)",
          "REITs",
          "Foreign private issuers (20-F and 40-F filers), with the limits below",
        ],
      },
      {
        kind: "p",
        text: "Every screen shows how many companies are in the universe and, step by step, how many each filter removes and how many it removed because the value was missing.",
      },
      {
        kind: "p",
        text: "**Share classes.** GOOG and GOOGL are one company. The primary ticker is the most liquid class. Market cap adds up every class at its own price where the classes trade at different prices (Berkshire), from a hand-maintained list.",
      },
    ],
  },
  {
    id: "period-rules",
    title: "Period rules",
    blocks: [
      {
        kind: "ul",
        items: [
          "**TTM (trailing twelve months)** is used for flows such as revenue, earnings and cash flow. It is the sum of the last four quarters, which must run back to back. Companies don't file a fourth quarter on its own, so Q4 = the fiscal year − the first nine months. If a quarter can't be built, TTM = the fiscal year + this year-to-date − last year's year-to-date of the same length. If none of that works, TTM is missing.",
          "**MRQ (most recent quarter)** is used for balance-sheet items such as cash, debt and equity: the value at the latest balance-sheet date.",
          "**FY** means fiscal-year series, used for multi-year tests (3- and 5-year growth, the Piotroski F-score, the five-year dividend record).",
          "**Averages** of balance-sheet items (for example in ROIC, ROA and the accruals ratio) are (now + one year earlier) / 2. The year-earlier value must be within 45 days of the same date a year before, or the metric is missing.",
          "**One date per company.** Every TTM metric for a company uses the same TTM end, and every balance-sheet metric uses the same MRQ date. If an item has no value at that date, it's missing. Glint never quietly uses an older value.",
          "Glint identifies each period by its start and end dates. The fiscal-year label on a filing describes the filing, and a 10-K's comparative columns carry the new filing's label.",
          "Restatements: the latest-filed value for a period wins.",
        ],
      },
    ],
  },
  {
    id: "applicability-matrix",
    title: "Applicability matrix",
    blocks: [
      {
        kind: "p",
        text: "Some metrics don't mean anything for some kinds of company. Glint shows those as **n/m** (not meaningful), and they never pass a filter.",
      },
      {
        kind: "table",
        head: ["Metric group", "Banks", "Insurance", "Capital markets", "REITs", "Utilities", "Foreign filers"],
        rows: [
          ["Gross margin, DIO/DPO/cash conversion cycle", "n/m", "n/m", "n/m", "ok", "ok", "ok"],
          [
            "EV-based (EV/EBIT, EBIT/EV, EV/EBITDA, EV/Sales), net debt / EBITDA",
            "n/m",
            "n/m",
            "n/m",
            "ok (FFO not available)",
            "ok",
            "n/m*",
          ],
          ["Current and quick ratio", "n/m", "n/m", "n/m", "ok", "ok", "ok"],
          ["ROIC, Greenblatt ROC", "n/m", "n/m", "n/m", "ok", "ok", "ok"],
          ["Altman Z", "n/m", "n/m", "n/m", "n/m", "ok", "n/m*"],
          ["Piotroski F", "n/m", "n/m", "ok", "ok", "ok", "ok"],
          ["P/E, P/B, ROE, dividend metrics", "ok", "ok", "ok", "ok (P/E is a weak REIT measure)", "ok", "n/m*"],
        ],
        foot: "* Price-based metrics for foreign filers, until currency conversion and ADR ratios are added. Each metric's rules are listed in the [metric dictionary](/metrics).",
      },
    ],
  },
  {
    id: "missing-and-not-meaningful-values",
    title: "Missing and not-meaningful values",
    blocks: [
      {
        kind: "p",
        text: "Glint never fills a gap with an estimate or a zero. Every empty cell carries a reason.",
      },
      {
        kind: "table",
        head: ["Shown as", "Code", "In plain English"],
        rows: [
          ["—", "`MISSING_INPUT`", "A number the formula needs isn't in the company's filings. The note names it."],
          [
            "—",
            "`INSUFFICIENT_HISTORY`",
            "Not enough periods yet: for example fewer than four quarters, fewer than five fiscal years, or less than a year of prices.",
          ],
          ["—", "`STALE_DATA`", "The inputs are older than the freshness limit, so the value would describe a different moment."],
          [
            "—",
            "`SMALL_PEER_GROUP`",
            "You asked for a comparison within a sector, but the sector has too few companies in the universe (fewer than 5).",
          ],
          [
            "n/m",
            "`NEGATIVE_DENOMINATOR`",
            "The ratio would divide by zero or a negative number: P/E with a loss, P/B with negative equity.",
          ],
          ["n/m", "`NOT_APPLICABLE_SECTOR`", "The metric doesn't apply to this kind of business (see the matrix above)."],
          [
            "n/m",
            "`FOREIGN_PRICE_BASIS`",
            "A foreign filer whose shares or currency don't match the US price, so a price ratio would mix bases.",
          ],
          [
            "n/m",
            "`NO_INTEREST_EXPENSE`",
            "Interest expense is reported as zero, or the company reports no debt, so interest coverage has nothing to cover. If interest expense simply isn't tagged, the value is missing (—) instead.",
          ],
          [
            "value ⓘ",
            "`DERIVED_INPUT`",
            "The value is real, but one input was derived (for example gross profit = revenue − cost of revenue).",
          ],
          [
            "value ⓘ",
            "`ASSUMED_TAX_RATE`",
            "The value is real, but ROIC used the 21% statutory tax rate because pretax income was zero or negative, so the company's own rate couldn't be worked out.",
          ],
          [
            "value ⓘ",
            "`INPUT_EXCLUDES`",
            "The value is real, but an input leaves out an item Glint can't place from the filing (for example a finance lease when the filing doesn't say which balance-sheet line holds it). The note says what and how much.",
          ],
        ],
      },
      {
        kind: "p",
        text: "In a screen, a missing or n/m value fails its filter unless the filter says “missing passes”. The funnel counts those removals separately.",
      },
    ],
  },
  {
    id: "sectors",
    title: "Sectors (SIC-based, not GICS)",
    blocks: [
      {
        kind: "ul",
        items: [
          "Sectors come from the SIC code a company registered with the SEC, mapped to Glint's 14 sectors. They are **not GICS** (licensed by MSCI and S&P), and the app labels them “Sector (SIC-based)”.",
          "SIC codes are chosen at registration and can be years out of date. A company that has changed business may sit in its old sector. Glint's Technology sector, for example, includes hardware and semiconductor makers as well as software.",
          "Manual corrections are kept in config, each with a reason, and every one is listed below.",
        ],
      },
    ],
  },
  {
    id: "foreign-filer-limits",
    title: "Foreign filer limits",
    blocks: [
      {
        kind: "ul",
        items: [
          "Companies filing 20-F or 40-F reports are in the universe and labelled.",
          "They often report under IFRS and in a currency other than dollars, and the US listing may be an ADR that represents several (or a fraction of an) ordinary share.",
          "Until Glint adds currency conversion and ADR ratios, **price-based metrics for foreign filers are n/m**. The exception is a filer that reports in dollars and lists its ordinary shares directly (for example Canadian 40-F filers).",
          "Fundamentals-only metrics (margins, growth, returns, balance-sheet health) are computed as usual. IFRS and US GAAP define some items differently, so compare them with care.",
          "Most foreign filers therefore have no market cap, so a screen with a market-cap bound or a price-based filter leaves them out.",
        ],
      },
    ],
  },
  {
    id: "survivorship-and-look-ahead",
    title: "Survivorship and look-ahead",
    blocks: [
      {
        kind: "ul",
        items: [
          "Glint has **no backtests** and never says what a screen “would have returned”.",
          "An honest backtest needs three things Glint doesn't have yet: fundamentals as they were known on each past date (point in time), the companies that have since been delisted, and those delisted companies' prices.",
          "**Survivorship bias:** today's universe holds only companies that still exist. Testing a screen on it leaves out the failures, which makes most screens look better than they were.",
          "**Look-ahead bias:** today's numbers include restatements and filings made after the dates being tested.",
          "Glint archives every build's metrics from day one, so a point-in-time history builds up over time.",
        ],
      },
    ],
  },
  {
    id: "presets",
    title: "Presets",
    blocks: [
      {
        kind: "p",
        text: "The 12 [presets](/presets) are starting points to adjust. Each one states its source (a book, paper or common heuristic), what it looks for and what it misses. Where Glint's version differs from the source, the preset says so. Thresholds were set so each preset returns a workable list on the current data. No preset claims any returns.",
      },
    ],
  },
];

export const CLOSING =
  "**Educational tool. Not investment advice.** Glint shows what the filings say and how its numbers are built. What to do with them is up to you.";
