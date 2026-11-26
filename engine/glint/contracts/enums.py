"""Shared enums. Every worktree builds against these; change them only via the §8.6 protocol."""

from enum import StrEnum


class LineItem(StrEnum):
    """Normalized financial line items (Appendix B), plus the derived items of §4.3 rule 9."""

    # Income statement (durations)
    REVENUE = "revenue"
    COST_OF_REVENUE = "cost_of_revenue"
    GROSS_PROFIT = "gross_profit"
    OPERATING_INCOME = "operating_income"
    PRETAX_INCOME = "pretax_income"
    INCOME_TAX = "income_tax"
    NET_INCOME = "net_income"
    INTEREST_EXPENSE = "interest_expense"
    DNA = "dna"
    SBC = "sbc"
    RND = "rnd"
    SGA = "sga"
    EPS_DILUTED = "eps_diluted"
    DILUTED_SHARES = "diluted_shares"
    # Cash flow (durations; capex, dividends and buybacks are positive outflows)
    CFO = "cfo"
    CAPEX = "capex"
    DIVIDENDS_PAID = "dividends_paid"
    BUYBACKS = "buybacks"
    STOCK_ISSUED = "stock_issued"
    DPS_DECLARED = "dps_declared"
    # Balance sheet (instants)
    CASH = "cash"
    ST_INVESTMENTS = "st_investments"
    RECEIVABLES = "receivables"
    INVENTORY = "inventory"
    CURRENT_ASSETS = "current_assets"
    TOTAL_ASSETS = "total_assets"
    PPE_NET = "ppe_net"
    GOODWILL = "goodwill"
    INTANGIBLES = "intangibles"
    ACCOUNTS_PAYABLE = "accounts_payable"
    CURRENT_LIABILITIES = "current_liabilities"
    TOTAL_LIABILITIES = "total_liabilities"
    DEBT_CURRENT = "debt_current"
    DEBT_NONCURRENT = "debt_noncurrent"
    PREFERRED = "preferred"
    MINORITY_INTEREST = "minority_interest"
    EQUITY = "equity"
    EQUITY_INCL_NCI = "equity_incl_nci"
    LIABILITIES_AND_EQUITY = "liabilities_and_equity"
    RETAINED_EARNINGS = "retained_earnings"
    SHARES_OUTSTANDING = "shares_outstanding"
    # Derived only (§4.3 rule 9; always flagged DERIVED_INPUT)
    TOTAL_DEBT = "total_debt"
    EBITDA = "ebitda"
    FCF = "fcf"


class Sector(StrEnum):
    """Glint sectors (SIC-based, Appendix C). Not GICS."""

    TECHNOLOGY = "Technology"
    COMMUNICATION = "Communication"
    CONSUMER_DISCRETIONARY = "Consumer Discretionary"
    CONSUMER_STAPLES = "Consumer Staples"
    HEALTH_CARE = "Health Care"
    INDUSTRIALS = "Industrials"
    MATERIALS = "Materials"
    ENERGY = "Energy"
    UTILITIES = "Utilities"
    REAL_ESTATE = "Real Estate"
    BANKS = "Banks"
    INSURANCE = "Insurance"
    CAPITAL_MARKETS = "Capital Markets"
    UNCLASSIFIED = "Unclassified"


FINANCIAL_SECTORS = frozenset({Sector.BANKS, Sector.INSURANCE, Sector.CAPITAL_MARKETS})


class Kind(StrEnum):
    OPERATING = "operating"
    SPAC = "spac"
    FUND = "fund"
    SHELL = "shell"
    # Every listed ticker is a debt or preferred security: no listed common stock to screen.
    NO_COMMON_EQUITY = "no_common_equity"
    SYNTHETIC = "synthetic"  # synthetic builds only; never mistaken for real data


class Exchange(StrEnum):
    NYSE = "NYSE"
    NASDAQ = "Nasdaq"
    NYSE_AMERICAN = "NYSE American"
    TXSE = "TXSE"  # Texas Stock Exchange (primary listings from Oct 2026)
    CBOE = "CBOE"
    OTC = "OTC"


DEFAULT_EXCHANGES = (Exchange.NYSE, Exchange.NASDAQ, Exchange.NYSE_AMERICAN, Exchange.TXSE)


class NoteCode(StrEnum):
    """Null reason codes (§2.4), one per null cell, stored in `metric_notes`."""

    MISSING_INPUT = "MISSING_INPUT"
    NEGATIVE_DENOMINATOR = "NEGATIVE_DENOMINATOR"
    NOT_APPLICABLE_SECTOR = "NOT_APPLICABLE_SECTOR"
    FOREIGN_PRICE_BASIS = "FOREIGN_PRICE_BASIS"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE_DATA = "STALE_DATA"
    NO_INTEREST_EXPENSE = "NO_INTEREST_EXPENSE"
    SMALL_PEER_GROUP = "SMALL_PEER_GROUP"
    DERIVED_INPUT = "DERIVED_INPUT"
    ASSUMED_TAX_RATE = "ASSUMED_TAX_RATE"
    INPUT_EXCLUDES = "INPUT_EXCLUDES"  # a real value whose input leaves out a known item


class NoteDisplay(StrEnum):
    MISSING = "—"
    NOT_MEANINGFUL = "n/m"
    VALUE_WITH_INFO = "value+info"


NOTE_DISPLAY: dict[NoteCode, NoteDisplay] = {
    NoteCode.MISSING_INPUT: NoteDisplay.MISSING,
    NoteCode.NEGATIVE_DENOMINATOR: NoteDisplay.NOT_MEANINGFUL,
    NoteCode.NOT_APPLICABLE_SECTOR: NoteDisplay.NOT_MEANINGFUL,
    NoteCode.FOREIGN_PRICE_BASIS: NoteDisplay.NOT_MEANINGFUL,
    NoteCode.INSUFFICIENT_HISTORY: NoteDisplay.MISSING,
    NoteCode.STALE_DATA: NoteDisplay.MISSING,
    NoteCode.NO_INTEREST_EXPENSE: NoteDisplay.NOT_MEANINGFUL,
    NoteCode.SMALL_PEER_GROUP: NoteDisplay.MISSING,
    NoteCode.DERIVED_INPUT: NoteDisplay.VALUE_WITH_INFO,
    NoteCode.ASSUMED_TAX_RATE: NoteDisplay.VALUE_WITH_INFO,
    NoteCode.INPUT_EXCLUDES: NoteDisplay.VALUE_WITH_INFO,
}

# Codes that annotate a present value rather than explain a null.
NON_NULL_NOTE_CODES = frozenset(
    {NoteCode.DERIVED_INPUT, NoteCode.ASSUMED_TAX_RATE, NoteCode.INPUT_EXCLUDES}
)


class Unit(StrEnum):
    USD = "usd"
    FRAC = "frac"  # 0.15 displays as 15.0%
    PP = "pp"  # percentage points, stored as a fraction: 0.02 = +2.0 pp
    X = "x"  # a multiple
    DAYS = "days"
    SCORE = "score"
    BOOL = "bool"
    TEXT = "text"  # categorical fields (sector, exchange, kind); not used by metrics


NUMERIC_UNITS = frozenset({Unit.USD, Unit.FRAC, Unit.PP, Unit.X, Unit.DAYS, Unit.SCORE})


class Basis(StrEnum):
    TTM = "ttm"  # trailing twelve months of flows
    MRQ = "mrq"  # most recent balance-sheet instant
    FY = "fy"  # fiscal-year series
    Q = "q"  # latest discrete quarter
    DAILY = "daily"  # price series
    MIXED = "mixed"  # combines bases (e.g. TTM flow over MRQ balance, or price × shares)
    BUILD = "build"  # computed at build time (coverage, days since filing, flag count)


class Tier(StrEnum):
    SEC = "sec"
    PRICE = "price"


class Category(StrEnum):
    SIZE_LIQUIDITY = "size_liquidity"
    VALUATION = "valuation"
    PROFITABILITY = "profitability"
    GROWTH = "growth"
    BALANCE_SHEET = "balance_sheet"
    EFFICIENCY = "efficiency"
    QUALITY = "quality"
    PRICE_MOMENTUM = "price_momentum"
    DATA_QUALITY = "data_quality"


class Better(StrEnum):
    """Direction used by percentile ranking: ↑ higher, ↓ lower, · neutral."""

    HIGHER = "higher"
    LOWER = "lower"
    NEUTRAL = "neutral"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"


class MetricStatus(StrEnum):
    PLANNED = "planned"
    LIVE = "live"


class Taxonomy(StrEnum):
    US_GAAP = "us-gaap"
    IFRS_FULL = "ifrs-full"
    DEI = "dei"


class PeriodKind(StrEnum):
    DURATION = "duration"
    INSTANT = "instant"


class FlagSeverity(StrEnum):
    """How to read a flag (`config/thresholds.yaml` `flags.<id>.severity`)."""

    CAUTION = "caution"  # about the business: dilution, coverage, cash
    INFO = "info"  # about reading the data: a stale or restated filing, a lagging share count


class FlagId(StrEnum):
    """Flags (§2.10). Questions, not verdicts."""

    DILUTION = "dilution"
    EARNINGS_WITHOUT_CASH = "earnings_without_cash"
    RECEIVABLES_OUTPACING = "receivables_outpacing"
    INVENTORY_BUILD = "inventory_build"
    GOODWILL_HEAVY = "goodwill_heavy"
    THIN_COVERAGE = "thin_coverage"
    STALE_FILING = "stale_filing"
    LATE_FILER = "late_filer"
    NEGATIVE_EQUITY = "negative_equity"
    HEAVY_SBC = "heavy_sbc"
    RESTATED = "restated"  # P1
    FY_CHANGE = "fy_change"
    MARKET_CAP_IMPLAUSIBLE = "market_cap_implausible"


class ApplicabilityScope(StrEnum):
    """Columns of the applicability matrix (§4.5)."""

    BANKS = "banks"
    INSURANCE = "insurance"
    CAPITAL_MARKETS = "capital_markets"
    REITS = "reits"
    UTILITIES = "utilities"
    FOREIGN_FILERS = "foreign_filers"
