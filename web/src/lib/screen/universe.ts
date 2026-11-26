import type { components } from "@/lib/api/types";
import { formatCount, formatUsdShort } from "@/lib/format";
import { DEFAULT_EXCHANGES, DEFAULT_UNIVERSE, effectiveUniverse } from "./defaults";

type Universe = components["schemas"]["Universe"];
type Kind = components["schemas"]["Kind"];
type UniverseRules = components["schemas"]["UniverseRules"];

export type UniverseChip = {
  key: keyof Universe | "scope";
  /** The rule in plain language ("Trades at least $1M a day"). */
  label: string;
  /** Patch that removes this rule (back to "no limit"), or null if the rule can't be removed. */
  clear: Partial<Universe> | null;
  /** Why a rule can't be removed. */
  lockReason?: string;
  /** More detail, for a tooltip or a second line. */
  hint?: string;
};

const KIND_LABEL: Record<Kind, string> = {
  spac: "SPACs",
  fund: "funds",
  shell: "shell companies",
  no_common_equity: "companies with no common stock",
  operating: "operating companies",
  synthetic: "synthetic companies",
};

function sameSet<T>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}

/** "A", "A and B", "A, B and C". */
function listOf(xs: readonly string[], last = "and"): string {
  return xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} ${last} ${xs[xs.length - 1]}`;
}

/**
 * The universe's rules in plain language (docs/ui-spec.md §7), in a stable order. Every rule that
 * narrows the universe is listed, so the screen never hides what it leaves out (principle 6).
 * `rules` is `/api/meta`'s `universe_rules`; until it has loaded, the stale rule names no number.
 */
export function universeChips(u: Universe | undefined, rules?: UniverseRules | null): UniverseChip[] {
  const e = effectiveUniverse(u);
  const chips: UniverseChip[] = [
    { key: "scope", label: "US companies that file with the SEC", clear: null, lockReason: "Glint covers SEC filers listed in the US." },
  ];
  const defaultExchanges = sameSet(e.exchanges, DEFAULT_EXCHANGES);
  chips.push({
    key: "exchanges",
    label: `Listed on ${listOf(e.exchanges, "or")}`,
    clear: defaultExchanges ? null : { exchanges: DEFAULT_EXCHANGES },
    lockReason: defaultExchanges ? "These are the US exchanges Glint covers." : undefined,
  });
  if (e.exclude_kinds.length > 0) {
    const all = sameSet(e.exclude_kinds, DEFAULT_UNIVERSE.exclude_kinds);
    const left = listOf(e.exclude_kinds.map((k) => KIND_LABEL[k] ?? k));
    chips.push({ key: "exclude_kinds", label: all ? "Operating companies only" : `Leaves out ${left}`, hint: `Leaves out ${left}.`, clear: { exclude_kinds: [] } });
  }
  if (e.sectors_include.length > 0) {
    chips.push({ key: "sectors_include", label: `Only ${listOf(e.sectors_include)}`, clear: { sectors_include: [] } });
  }
  if (e.sectors_exclude.length > 0) {
    chips.push({ key: "sectors_exclude", label: `Leaves out ${listOf(e.sectors_exclude)}`, clear: { sectors_exclude: [] } });
  }
  if (e.market_cap_min !== null && e.market_cap_max !== null) {
    chips.push({
      key: "market_cap_min",
      label: `Market cap ${formatUsdShort(e.market_cap_min)} to ${formatUsdShort(e.market_cap_max)}`,
      clear: { market_cap_min: null, market_cap_max: null },
    });
  } else if (e.market_cap_min !== null) {
    chips.push({ key: "market_cap_min", label: `Market cap at least ${formatUsdShort(e.market_cap_min)}`, clear: { market_cap_min: null } });
  } else if (e.market_cap_max !== null) {
    chips.push({ key: "market_cap_max", label: `Market cap at most ${formatUsdShort(e.market_cap_max)}`, clear: { market_cap_max: null } });
  }
  if (e.avg_dollar_volume_min !== null) {
    chips.push({
      key: "avg_dollar_volume_min",
      label: `Trades at least ${formatUsdShort(e.avg_dollar_volume_min)} a day`,
      hint: "Average daily dollar volume over three months.",
      clear: { avg_dollar_volume_min: null },
    });
  }
  if (!e.include_foreign_filers) chips.push({ key: "include_foreign_filers", label: "No foreign private issuers", clear: { include_foreign_filers: true } });
  // The stale window comes from config/thresholds.yaml via /api/meta (principle 8: never a number
  // in code). Before meta has loaded, the label names no number rather than guess one.
  if (!e.include_stale) {
    const months = rules?.stale_annual_report_months;
    chips.push(
      months == null
        ? {
            key: "include_stale",
            label: "Only companies with a recent annual report",
            hint: "Companies whose latest annual report is older than the build's stale window are left out.",
            clear: { include_stale: true },
          }
        : {
            key: "include_stale",
            label: `Only companies with an annual report in the last ${formatCount(months)} months`,
            hint: `Companies whose latest annual report is more than ${formatCount(months)} months old are left out.`,
            clear: { include_stale: true },
          },
    );
  }
  if (!e.include_no_facts)
    chips.push({
      key: "include_no_facts",
      label: "Only companies with XBRL financials",
      clear: null,
      lockReason: "Glint only screens companies whose filings include XBRL financial statements.",
    });
  if (e.max_days_since_filing !== null) {
    chips.push({
      key: "max_days_since_filing",
      label: `Filed in the last ${formatCount(e.max_days_since_filing)} days`,
      clear: { max_days_since_filing: null },
    });
  }
  return chips;
}

export { DEFAULT_UNIVERSE };
