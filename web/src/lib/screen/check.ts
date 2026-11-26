import type { components } from "@/lib/api/types";
import { isGroup, type Condition, type Group, type Screen } from "./types";

type Outcome = components["schemas"]["FilterOutcome"];

export type FilterCheck = {
  /** Top-level filter index (the sieve step it is). */
  index: number;
  node: Condition | Group;
  /** Null when the API sent no outcome for one of its leaves. */
  passed: boolean | null;
};

export type ScreenCheck = {
  /** False when the company is outside the screen's universe (its filters weren't evaluated). */
  inUniverse: boolean;
  filters: FilterCheck[];
  passedCount: number;
  failed: FilterCheck[];
};

/**
 * Rolls `why_passed` (one outcome per filter *leaf*) up to the screen's top-level filters, the
 * unit the sieve and the "Passes 3 of 5" heading count in: an OR group passes when any child does,
 * an AND group when every child does.
 */
export function screenCheck(screen: Screen, outcomes: Outcome[]): ScreenCheck {
  const byPath = new Map(outcomes.map((o) => [o.filter_path.join("."), o.passed]));
  const inUniverse = byPath.get("universe") !== false;
  const passedAt = (node: Condition | Group, path: (string | number)[]): boolean | null => {
    if (!isGroup(node)) return byPath.get(path.join(".")) ?? null;
    const parts = (node.children ?? []).map((c, j) => passedAt(c, [...path, "children", j]));
    if (parts.some((p) => p === null)) return null;
    return node.op === "or" ? parts.some(Boolean) : parts.every(Boolean);
  };
  const filters = (screen.filters?.children ?? []).map((node, index) => ({
    index,
    node,
    passed: inUniverse ? passedAt(node, ["filters", "children", index]) : null,
  }));
  return {
    inUniverse,
    filters,
    passedCount: filters.filter((f) => f.passed === true).length,
    failed: filters.filter((f) => f.passed === false),
  };
}
