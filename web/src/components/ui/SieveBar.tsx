"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import type { components } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { useScrollEdges } from "@/lib/useScrollEdges";
import { useTickedNumber } from "@/lib/useTickedNumber";

export type FunnelStep = components["schemas"]["FunnelStep"];

/**
 * The sieve (docs/ui-spec.md §4.3), Glint's one memorable element. Each stage's bar spans the
 * whole universe, so every stage is read against the same frame: kept (forest), failed the test
 * (line), removed for missing data (hatched), and the part earlier stages already took (empty).
 * The stage that removes the most says so in words, with the cause when missing data dominates.
 */
export const SieveBar = memo(function SieveBar({
  steps,
  onSelect,
  selected = null,
  dimmed = false,
  labelFor = (s) => s.label,
  missingName,
}: {
  steps: FunnelStep[];
  onSelect?: (step: FunnelStep) => void;
  /** The stage whose removed companies are open below. */
  selected?: number | null;
  dimmed?: boolean;
  /** Display label per step; defaults to the API's. */
  labelFor?: (step: FunnelStep) => string;
  /** Metric name for "2,777 have no ROIC" (top-level conditions only). */
  missingName?: (step: FunnelStep) => string | null;
}) {
  const scroller = useRef<HTMLOListElement>(null);
  useScrollEdges(scroller);
  // The one orchestrated moment: the trays fill once, on first load.
  const [fill, setFill] = useState(true);
  useEffect(() => {
    const t = setTimeout(() => setFill(false), 600);
    return () => clearTimeout(t);
  }, []);
  const universe = steps[0]?.remaining ?? 0;

  return (
    <ol
      ref={scroller}
      aria-label="Sieve: companies kept after each filter"
      className={`fade-x flex items-stretch gap-1 overflow-x-auto pb-1 transition-opacity duration-200 ease-out ${dimmed ? "opacity-50" : ""}`}
    >
      {steps.map((step, i) => (
        <li key={step.index} className="flex min-w-36 shrink-0 items-stretch gap-1">
          <Stage
            step={step}
            universe={universe}
            label={labelFor(step)}
            missing={missingName?.(step) ?? null}
            selected={selected === step.index}
            onSelect={onSelect}
            fill={fill}
            delay={i * 50}
          />
          {i < steps.length - 1 && (
            <span aria-hidden className="self-center text-meta text-muted">
              <Icon name="chevron-right" />
            </span>
          )}
        </li>
      ))}
    </ol>
  );
});

function Stage({
  step,
  universe,
  label,
  missing,
  selected,
  onSelect,
  fill,
  delay,
}: {
  step: FunnelStep;
  universe: number;
  label: string;
  missing: string | null;
  selected: boolean;
  onSelect?: (step: FunnelStep) => void;
  fill: boolean;
  delay: number;
}) {
  const tipId = useId();
  const isUniverse = step.index === 0;
  const { shown, changed } = useTickedNumber(step.remaining);
  const failed = step.removed - step.removed_missing;
  const pct = (n: number) => (universe > 0 ? `${Math.max(n > 0 ? 0.6 : 0, (n / universe) * 100)}%` : "0%");
  const missingDominates = step.binding && step.removed > 0 && step.removed_missing > step.removed / 2;
  const spoken = isUniverse
    ? `Universe: ${formatCount(step.remaining)} companies, ${formatCount(step.removed)} outside the universe${step.removed_missing > 0 ? `, ${formatCount(step.removed_missing)} of them for missing data` : ""}.`
    : `${label}: ${formatCount(step.remaining)} kept, ${formatCount(failed)} failed, ${formatCount(step.removed_missing)} had no data.${step.binding ? " Removes the most." : ""}`;

  return (
    <button
      type="button"
      onClick={() => onSelect?.(step)}
      disabled={!onSelect}
      aria-label={spoken}
      aria-describedby={tipId}
      aria-expanded={isUniverse ? undefined : selected}
      className={`group relative flex w-full max-w-64 flex-col gap-1.5 rounded-panel bg-paper px-3 py-2 text-left transition-colors duration-150 ease-out enabled:hover:bg-dune/50 ${
        selected ? "shadow-[inset_0_-2px_0_var(--purple)]" : ""
      }`}
    >
      <span className="truncate text-label text-ink-soft">{label}</span>
      <span className={`num text-figure font-semibold text-ink decoration-purple decoration-2 underline-offset-4 ${changed ? "underline" : ""}`}>{formatCount(shown)}</span>
      {/* The bar is the universe; segments are linear, so trays compare against one frame. */}
      <span aria-hidden className="relative flex h-2.5 w-full overflow-hidden rounded-control shadow-[inset_0_0_0_1px_var(--line)]">
        <span
          className={`h-full bg-forest transition-[width] duration-200 ease-out ${fill ? "origin-left animate-[sieve-fill_400ms_var(--ease-out)_both]" : ""}`}
          style={{ width: pct(step.remaining), animationDelay: `${delay}ms` }}
        />
        {!isUniverse && <span className="h-full bg-line-strong/30 transition-[width] duration-200 ease-out" style={{ width: pct(failed) }} />}
        {!isUniverse && <span className="hatch h-full transition-[width] duration-200 ease-out" style={{ width: pct(step.removed_missing) }} />}
      </span>
      <span className="num text-meta text-muted">
        {isUniverse ? `${formatCount(step.removed)} outside the universe` : step.removed > 0 ? `removes ${formatCount(step.removed)}` : "removes none"}
      </span>
      {step.binding && (
        <span className="text-meta text-ink">
          removes the most{missingDominates && missing ? `: ${formatCount(step.removed_missing)} have no ${missing}` : ""}
        </span>
      )}
      <span
        id={tipId}
        role="tooltip"
        className="pointer-events-none absolute top-full left-0 z-30 mt-1.5 hidden w-60 rounded-panel bg-paper px-3 py-2 text-meta text-ink-soft shadow-overlay group-hover:block group-focus-visible:block"
      >
        {isUniverse ? (
          <>
            <span className="block">{formatCount(step.remaining)} companies in the universe.</span>
            <span className="block">{formatCount(step.removed)} in this build are outside it.</span>
          </>
        ) : (
          <>
            <span className="num block">{formatCount(step.remaining)} kept</span>
            <span className="num block">{formatCount(failed)} failed the test</span>
            <span className="num block">{formatCount(step.removed_missing)} had no data</span>
            {step.binding && <span className="mt-1 block">This filter removes the most companies, so loosening it, or letting missing values pass, changes the result most.</span>}
            <span className="mt-1 block text-muted">Select to see the companies it removed.</span>
          </>
        )}
      </span>
    </button>
  );
}
