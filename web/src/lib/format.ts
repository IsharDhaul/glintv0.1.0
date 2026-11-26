// The only place numbers and dates become strings (SPEC §3.3), enforced by
// no-stray-formatting.test.ts. Values arrive in storage units (fractions for frac/pp);
// this module only renders them. Input parsing and display↔storage conversion live in units.ts.

import type { components } from "./api/types";

export type Unit = components["schemas"]["Unit"];

const MINUS = "−";

const countFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const fixed = (digits: number) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: true });
const fixed0 = fixed(0);
const fixed1 = fixed(1);
const fixed2 = fixed(2);

/** "-1.2" → "−1.2": typographic minus everywhere. */
function signed(s: string): string {
  return s.startsWith("-") ? MINUS + s.slice(1) : s;
}

/** Avoid "−0.0%" when a tiny negative rounds to zero. */
function noNegZero(s: string): string {
  return /^-0(\.0+)?$/.test(s) ? s.slice(1) : s;
}

/** Company counts in the sieve, histograms and badges: 6,000. */
export function formatCount(n: number): string {
  return countFmt.format(n);
}

const USD_SCALES: [number, string][] = [
  [1e12, "T"],
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];

/** $1.24B / $312M / $9.38: three significant digits above $1,000. */
export function formatUsd(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? MINUS : "";
  for (const [scale, suffix] of USD_SCALES) {
    // Round first so 999.96M becomes $1.00B rather than $1000M.
    if (abs >= scale * 0.9995) {
      const scaled = abs / scale;
      const digits = scaled >= 99.95 ? 0 : scaled >= 9.995 ? 1 : 2;
      return `${sign}$${fixed(digits).format(scaled)}${suffix}`;
    }
  }
  return `${sign}$${fixed2.format(abs)}`;
}

/** A dollar amount in a sentence, trailing zeros dropped: $1M, $2B, $1.5B, $312M. */
export function formatUsdShort(v: number): string {
  return formatUsd(v).replace(/\.0+(?=[KMB]$)/, "").replace(/(\.\d*?)0+(?=[KMB]$)/, "$1");
}

/** 0.152 → "15.2%". */
export function formatFrac(v: number): string {
  return signed(noNegZero(fixed1.format(v * 100))) + "%";
}

/** 0.023 → "+2.3 pp" (always signed). */
export function formatPp(v: number): string {
  const s = noNegZero(fixed1.format(v * 100));
  return (s.startsWith("-") ? MINUS + s.slice(1) : s === "0.0" ? s : "+" + s) + " pp";
}

/** 14.2 → "14.2x". */
export function formatMultiple(v: number): string {
  return signed(noNegZero(fixed1.format(v))) + "x";
}

/** 47 → "47 d". */
export function formatDays(v: number): string {
  return signed(noNegZero(fixed0.format(v))) + " d";
}

/** Integer scores with a known maximum render as "7/9"; anything else to 2 dp. */
export function formatScore(v: number, max?: number): string {
  if (max !== undefined && Number.isInteger(v)) return `${v}/${max}`;
  return signed(noNegZero(fixed2.format(v)));
}

export function formatBool(v: boolean): string {
  return v ? "Yes" : "No";
}

// Score metrics with a fixed integer scale, shown as "7/9". The contract has no scale field yet
// (see docs/decisions/WT-05.md, contract gap 4); this is display metadata, not a threshold.
const SCORE_MAX: Record<string, number> = { piotroski_f: 9 };
// Score metrics that are plain counts ("2", not "2.00"); same caveat as SCORE_MAX.
const COUNT_METRICS: ReadonlySet<string> = new Set(["flag_count"]);

/**
 * A gap between a value and a threshold, in the metric's own unit and without a sign (the words
 * around it say which way): percents as percentage points ("7.5 pp"), multiples "0.4x", "$120M", "12 d".
 */
export function formatGap(unit: Unit, gap: number): string {
  const g = Math.abs(gap);
  // A real gap that rounds to zero still isn't zero: say "< 0.1".
  if (unit === "frac" || unit === "pp") return g > 0 && g * 100 < 0.05 ? "< 0.1 pp" : `${fixed1.format(g * 100)} pp`;
  if (unit === "x" && g > 0 && g < 0.05) return "< 0.1x";
  return formatValue(unit, g);
}

/** A gap between two percentiles (fractions of the ranking): 0.03 → "3.0 pts". */
export function formatPercentilePoints(gap: number): string {
  return `${fixed1.format(Math.abs(gap) * 100)} pts`;
}

/** A share price: always two decimals ("$512.40", "$9.38", "$1,204.00"). */
export function formatPrice(v: number): string {
  return `${v < 0 ? MINUS : ""}$${fixed2.format(Math.abs(v))}`;
}

/** A percentile (0..1) in compact form: 0.873 → "p87". */
export function formatPercentile(p: number): string {
  return `p${countFmt.format(Math.round(Math.min(1, Math.max(0, p)) * 100))}`;
}

/**
 * A percentile said with its direction, from the metric's `better`: higher-is-better p87 →
 * "better than 87% of Technology"; lower-is-better p87 → "better than 13% of Technology";
 * neutral p87 → "higher than 87% of Technology".
 */
export function describePercentile(p: number, better: "higher" | "lower" | "neutral", scope: string): string {
  const pct = Math.round(Math.min(1, Math.max(0, p)) * 100);
  if (better === "neutral") return `higher than ${countFmt.format(pct)}% of ${scope}`;
  return `better than ${countFmt.format(better === "higher" ? pct : 100 - pct)}% of ${scope}`;
}

/** Format a metric's non-null value using its definition (unit, score scale, counts). */
export function formatMetric(def: { id: string; unit: Unit }, v: number | boolean | string): string {
  if (COUNT_METRICS.has(def.id) && typeof v === "number" && Number.isInteger(v)) return formatCount(v);
  return formatValue(def.unit, v, { scoreMax: SCORE_MAX[def.id] });
}

// Dates: fixed locale and time zone, so server and browser render identical text.
const dateFmt = new Intl.DateTimeFormat("en-CA", { timeZone: "UTC", year: "numeric", month: "2-digit", day: "2-digit" });
const etFmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function parseDate(iso: string): Date | null {
  // Bare dates ("2026-01-01") are calendar dates: pin them to UTC midnight.
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "2026-01-01" or any ISO timestamp → "2026-01-01" (the UTC calendar date). */
export function formatDate(iso: string | null | undefined): string {
  const d = iso ? parseDate(iso) : null;
  return d ? dateFmt.format(d) : "—";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** SEC fiscal year end "MMDD" ("1231", "0630") → "Dec 31"; anything else as given. */
export function formatFiscalYearEnd(mmdd: string | null | undefined): string {
  const m = mmdd ? /^(\d{2})(\d{2})$/.exec(mmdd) : null;
  const month = m ? MONTHS[Number(m[1]) - 1] : undefined;
  if (!m || !month) return mmdd ?? "—";
  return `${month} ${Number(m[2])}`;
}

/** ISO timestamp → "2026-01-02 03:00 ET" (SPEC §2.11 freshness line). */
export function formatDateTimeEt(iso: string | null | undefined): string {
  const d = iso ? parseDate(iso) : null;
  if (!d) return "—";
  const parts = Object.fromEntries(etFmt.formatToParts(d).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ET`;
}

/**
 * Format any non-null metric value by unit. Null handling ("—" / "n/m") belongs to NullValue,
 * because it needs the reason code.
 */
export function formatValue(unit: Unit, v: number | boolean | string, opts: { scoreMax?: number } = {}): string {
  if (typeof v === "boolean") return formatBool(v);
  if (typeof v === "string") return v;
  if (!Number.isFinite(v)) return "n/m";
  switch (unit) {
    case "usd":
      return formatUsd(v);
    case "frac":
      return formatFrac(v);
    case "pp":
      return formatPp(v);
    case "x":
      return formatMultiple(v);
    case "days":
      return formatDays(v);
    case "score":
      return formatScore(v, opts.scoreMax);
    case "bool":
      return formatBool(v !== 0);
    case "text":
      return String(v);
  }
}
