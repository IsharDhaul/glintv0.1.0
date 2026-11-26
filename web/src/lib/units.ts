// The one place display units become storage units and back (SPEC §3.3).
// Storage: frac and pp are fractions (0.15, 0.02); everything else is as-is. The user types
// display units ("15" for 15%, "+2" for +2 pp, "1.5B" for $1.5B), converted exactly once here.

import type { Unit } from "./format";

/** Units whose display value is storage × 100. */
const PERCENT_UNITS: ReadonlySet<Unit> = new Set(["frac", "pp"]);

const USD_SUFFIX: Record<string, number> = { k: 1e3, m: 1e6, b: 1e9, t: 1e12 };

/** Strip float noise from ×/÷ 100 (0.07 × 100 = 7.000000000000001) without formatting. */
function clean(v: number): number {
  return Math.round(v * 1e9) / 1e9;
}

/** Storage → the number shown in an input box (0.15 → 15). */
export function toDisplay(unit: Unit, storage: number): number {
  return PERCENT_UNITS.has(unit) ? clean(storage * 100) : storage;
}

/** Display number → storage (15 → 0.15). */
export function toStorage(unit: Unit, display: number): number {
  return PERCENT_UNITS.has(unit) ? clean(display / 100) : display;
}

/** What the input shows beside the number. */
export function inputAffix(unit: Unit): { prefix?: string; suffix?: string } {
  switch (unit) {
    case "frac":
      return { suffix: "%" };
    case "pp":
      return { suffix: "pp" };
    case "x":
      return { suffix: "x" };
    case "days":
      return { suffix: "d" };
    case "usd":
      return { prefix: "$" };
    default:
      return {};
  }
}

/**
 * Parse what the user typed, in display units, into a storage value, or null if it isn't a
 * number. Accepts "15", "15%", "+2.3 pp", "−5" (typographic minus), "1,234", "14.2x" and,
 * for usd, magnitude suffixes: "300M", "$1.5b", "2T".
 */
export function parseInput(unit: Unit, text: string): number | null {
  let s = text.trim().toLowerCase().replace(/−/g, "-").replace(/[,\s]/g, "");
  if (unit === "usd") s = s.replace(/^([+-]?)\$/, "$1");
  s = s.replace(/(%|pp|x|d)$/, "");
  let mult = 1;
  if (unit === "usd") {
    const suffix = s.at(-1);
    if (suffix && suffix in USD_SUFFIX) {
      mult = USD_SUFFIX[suffix] as number;
      s = s.slice(0, -1);
    }
  }
  if (!/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/.test(s)) return null;
  const n = Number(s) * mult;
  return Number.isFinite(n) ? toStorage(unit, n) : null;
}

/**
 * Storage value → the text to prefill an input with: 0.15 → "15", 1.5e9 → "1.5B".
 * Always something parseInput reads back to the same value.
 */
export function inputText(unit: Unit, storage: number | null | undefined): string {
  if (storage === null || storage === undefined || !Number.isFinite(storage)) return "";
  if (unit === "usd") {
    for (const [suffix, scale] of [["T", 1e12], ["B", 1e9], ["M", 1e6], ["K", 1e3]] as const) {
      const scaled = storage / scale;
      // Only use a suffix when it's exact to 4 decimals, so the round trip is lossless.
      if (Math.abs(scaled) >= 1 && clean(scaled * 1e4) === Math.round(scaled * 1e4)) return `${clean(scaled)}${suffix}`;
    }
  }
  return String(toDisplay(unit, storage));
}

/**
 * A threshold picked by dragging, rounded to a step someone would type: 0.1% for percents and
 * pp, 0.1x for multiples, whole days, two decimals for scores, three significant figures for
 * dollars. Display-layer rounding of the user's own input, never of a metric value.
 */
export function roundForInput(unit: Unit, storage: number): number {
  if (!Number.isFinite(storage)) return storage;
  switch (unit) {
    case "frac":
    case "pp":
      return clean(Math.round(storage * 1000) / 1000);
    case "x":
      return clean(Math.round(storage * 10) / 10);
    case "days":
      return Math.round(storage);
    case "usd": {
      if (storage === 0) return 0;
      const mag = 10 ** (Math.floor(Math.log10(Math.abs(storage))) - 2);
      return clean(Math.round(storage / mag) * mag);
    }
    default:
      return clean(Math.round(storage * 100) / 100);
  }
}
