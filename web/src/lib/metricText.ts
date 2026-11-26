import { plainText } from "./labels";

/**
 * A registry definition split for display: its first sentence is the formula (set in mono), the
 * rest is how inputs and nulls are handled (set in the sans). "fcf_ttm / market_cap. Keeps
 * negatives." → { formula: "fcf_ttm / market_cap", rules: "Keeps negatives." }
 */
export function splitDefinition(definition: string): { formula: string; rules: string } {
  const text = plainText(definition).trim();
  // A sentence ends at ". " before a capital or an opening bracket; decimals ("0.5") don't match.
  const m = /\.\s+(?=[A-Z(])/.exec(text);
  if (!m) return { formula: text.replace(/\.$/, ""), rules: "" };
  return { formula: text.slice(0, m.index), rules: text.slice(m.index + 1).trim() };
}

/**
 * How to set a formula (the craft rule: Plex Mono for code only). `expr` is the expression; a
 * trailing worded aside ("(capex is a positive outflow in XBRL)") moves to `note`. `code` is true
 * when the expression is symbolic (an operator, and at most 8 plain words outside identifiers),
 * so it sets in mono; a formula written as a sentence sets in the word face.
 */
export function formulaParts(formula: string): { expr: string; note: string; code: boolean } {
  const words = (t: string) => (t.replace(/\w*_\w*/g, "").match(/[A-Za-z]{3,}/g) ?? []).length;
  const m = /^(.*\S)\s+\(([^()]*)\)$/.exec(formula);
  const split = m && words(m[2] ?? "") >= 2;
  const expr = split ? (m[1] ?? formula) : formula;
  const note = split ? (m[2] ?? "") : "";
  const code = /[/×÷+−=^√·*]/.test(expr) && words(expr) <= 8;
  return { expr, note, code };
}

/** The dictionary entry for a metric. */
export const metricHref = (id: string) => `/metrics#${encodeURIComponent(id)}`;
