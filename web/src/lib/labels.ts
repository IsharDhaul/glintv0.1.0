import type { components } from "./api/types";

type S = components["schemas"];

// Plain-English names for registry enums, shared by the picker, dictionary and company view.

export const CATEGORY_LABEL: Record<S["Category"] | "classification", string> = {
  size_liquidity: "Size & liquidity",
  valuation: "Valuation",
  profitability: "Profitability",
  growth: "Growth",
  balance_sheet: "Balance sheet",
  efficiency: "Efficiency",
  quality: "Quality",
  price_momentum: "Price & momentum",
  data_quality: "Data quality",
  classification: "Classification",
};

export const CATEGORY_ORDER = Object.keys(CATEGORY_LABEL) as (S["Category"] | "classification")[];

export const BASIS_LABEL: Record<S["Basis"], string> = {
  ttm: "TTM (trailing twelve months)",
  mrq: "MRQ (most recent quarter)",
  fy: "FY (fiscal year)",
  q: "Quarter",
  daily: "Daily",
  mixed: "Mixed (price and filings)",
  build: "Build",
};

export const UNIT_LABEL: Record<S["Unit"], string> = {
  usd: "US dollars",
  frac: "percent",
  pp: "percentage points",
  x: "multiple (x)",
  days: "days",
  score: "score",
  bool: "yes / no",
  text: "text",
};

export const BETTER_LABEL: Record<S["Better"], string> = { higher: "↑ higher is better", lower: "↓ lower is better", neutral: "· neutral" };

export const TIER_LABEL: Record<S["Tier"], string> = { sec: "SEC filings (tier 1)", price: "needs a market price (tier 2)" };

export const SCOPE_LABEL: Record<S["ApplicabilityScope"], string> = {
  banks: "Banks",
  insurance: "Insurance",
  capital_markets: "Capital markets",
  reits: "REITs",
  utilities: "Utilities",
  foreign_filers: "Foreign filers",
};

// Registry text (config/metrics.yaml) is written for maintainers: it names null-reason codes,
// spec sections and config files. On user-facing pages those become plain words. Display only:
// the registry, the API and docs/metrics.md keep the precise wording.
const PLAIN_REWRITES: [RegExp, string][] = [
  [/Until F20 \(FX \+ ADR ratios\):/g, "Until currency and ADR conversion is supported:"],
  [/null with FOREIGN_PRICE_BASIS/gi, "not meaningful"],
  [/\bnull \((NEGATIVE_DENOMINATOR|NO_INTEREST_EXPENSE)\)/gi, "not meaningful"],
  [/\bnull \((INSUFFICIENT_HISTORY|MISSING_INPUT)\)/gi, "missing"],
  [/\((INSUFFICIENT_HISTORY|MISSING_INPUT)\)/g, "missing"],
  [/with note ASSUMED_TAX_RATE/g, "and noted"],
  [/the ⓘ says so: INPUT_EXCLUDES/g, "a note on the value says so"],
  [/\(DERIVED_INPUT\)/g, "(noted as derived)"],
  [/, DERIVED_INPUT\)/g, ", noted as derived)"],
  [/\bSTALE_DATA\b/g, "marked stale"],
  [/\b(MISSING_INPUT|INSUFFICIENT_HISTORY|SMALL_PEER_GROUP)\b/g, "missing"],
  [/\b(NEGATIVE_DENOMINATOR|NOT_APPLICABLE_SECTOR|FOREIGN_PRICE_BASIS|NO_INTEREST_EXPENSE)\b/g, "not meaningful"],
  [/\b(DERIVED_INPUT|ASSUMED_TAX_RATE|INPUT_EXCLUDES)\b/g, "noted"],
  [/\s*\(§[\d.]+(?: rules? [\d–-]+)?\)/g, ""],
  [/§[\d.]+(?: rules? [\d–-]+)?:\s*/g, ""],
  [/ in config\/share_classes\.yaml/g, " on Glint's share-class list"],
  [/\s*The \w+ parts are stored in metric_history as \S+\./g, ""],
];

/** Registry prose for people: no reason codes, spec section numbers or config paths. */
export function plainText(s: string): string {
  let out = s;
  for (const [re, to] of PLAIN_REWRITES) {
    const text = out;
    out = text.replace(re, (...args: unknown[]) => {
      // A rewrite that starts a sentence starts with a capital ("Null (…)" → "Not meaningful").
      const offset = args.at(-2) as number;
      const startsSentence = /(^|\.\s+)$/.test(text.slice(0, offset));
      return startsSentence && to ? to[0]!.toUpperCase() + to.slice(1) : to;
    });
  }
  return out;
}
