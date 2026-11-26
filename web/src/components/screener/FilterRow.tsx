"use client";

import { Icon } from "@/components/ui/Icon";
import { memo, useId, type ReactNode } from "react";
import { IconButton } from "@/components/ui/Button";
import { Histogram, type Distribution } from "@/components/ui/Histogram";
import { Tooltip } from "@/components/ui/Tooltip";
import { MetricTip } from "@/components/ui/MetricTip";
import { metricHref } from "@/lib/metricText";
import Link from "next/link";
import type { components } from "@/lib/api/types";
import { formatCount, type Unit } from "@/lib/format";
import { describeCondition } from "@/lib/screen/describe";
import { allowedComparators, CMP_LABEL, CMP_WORDS, FILTER_FIELDS, isComplete, unitOf, valueKind, vsMedianUnit, withComparator } from "@/lib/screen/filters";
import type { NodePath } from "@/lib/screen/filters";
import type { Comparator, Condition, MetricDefinition, Sector } from "@/lib/screen/types";
import type { PickTarget } from "./FilterPanel";
import { UnitInput } from "./UnitInput";

type FunnelStep = components["schemas"]["FunnelStep"];

const SELECT = "h-ctl rounded-control border border-line-strong bg-paper px-1.5 text-label";
const FLIP: Partial<Record<Comparator, Comparator>> = { gte: "lte", lte: "gte", gt: "lt", lt: "gt" };

/**
 * One filter as one line (docs/ui-spec.md §4.1): metric, an operator you click to flip, the
 * threshold, the kept count, remove. Expanding shows the comparator, the missing-values toggle
 * and the histogram with a draggable threshold.
 */
export const FilterRow = memo(FilterRowView, (a, b) => {
  // A row re-renders only when what it shows changes: its condition, counts, distribution or
  // open state (handlers are stable, step objects are new on every evaluation).
  const k = (s: FunnelStep | null) => (s ? `${s.remaining}/${s.removed}/${s.removed_missing}/${s.binding}` : "");
  return a.cond === b.cond && k(a.step) === k(b.step) && a.dist === b.dist && a.expanded === b.expanded && a.inGroup === b.inGroup && a.metrics === b.metrics && a.sectors === b.sectors && a.path.top === b.path.top && a.path.child === b.path.child;
});

function FilterRowView({
  path,
  cond,
  metrics,
  sectors,
  step,
  dist,
  expanded,
  onToggle,
  onUpdate,
  onRemovePath,
  onPick,
  inGroup = false,
}: {
  path: NodePath;
  cond: Condition;
  metrics: Map<string, MetricDefinition>;
  sectors: Sector[];
  /** This filter's sieve step (top-level filters that ran). */
  step: FunnelStep | null;
  /** Distribution over the current universe, when the column data is loaded. */
  dist: Distribution | null;
  expanded: boolean;
  /** Stable handlers that take the row's path (so unchanged rows skip re-rendering). */
  onToggle: (path: NodePath) => void;
  onUpdate: (path: NodePath, c: Condition) => void;
  onRemovePath: (path: NodePath) => void;
  onPick: (target: PickTarget) => void;
  inGroup?: boolean;
}) {
  const onToggleExpanded = () => onToggle(path);
  const onChange = (c: Condition) => onUpdate(path, c);
  const onRemove = () => onRemovePath(path);
  const onChangeMetric = () => onPick({ mode: "replace", path });

  const def = metrics.get(cond.metric);
  const unit = unitOf(cond.metric, metrics);
  const name = def?.name ?? FILTER_FIELDS[cond.metric]?.name ?? cond.metric;
  const kind = valueKind(cond.cmp, unit);
  const complete = isComplete(cond, unit);
  const set = (patch: Partial<Condition>) => onChange({ ...cond, ...patch });
  const flip = FLIP[cond.cmp];
  const bodyId = useId();
  const summary = complete ? describeCondition(cond, metrics) : `${name}: needs a value`;
  const hint = incompleteHint(cond, kind);
  const numeric = def !== undefined && kind === "number";
  const tip = def ? <MetricTip def={def} more={false} /> : "Glint sector (from the SIC code)";

  return (
    <div role="group" aria-label={`Filter: ${summary}`} className="group/row">
      {/* Fixed columns, so thresholds and counts line up from row to row. */}
      <div className={`grid min-h-ctl items-center gap-x-1.5 py-1 ${inGroup ? "grid-cols-[1.5rem_minmax(0,1fr)_1.75rem_4.75rem_1.75rem]" : "grid-cols-[1.5rem_minmax(0,1fr)_1.75rem_4.75rem_2.75rem_1.75rem]"}`}>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={bodyId}
          aria-label={`${expanded ? "Collapse" : "Expand"} ${name}`}
          onClick={onToggleExpanded}
          className="inline-flex size-6 items-center justify-center rounded-control text-muted hover:text-ink"
        >
          <span aria-hidden className={`text-meta transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}>
            <Icon name="chevron-right" />
          </span>
        </button>
        <Tooltip tip={tip} side="bottom" className="min-w-0">
          {(describedBy) => (
            <button
              type="button"
              {...describedBy}
              onClick={onChangeMetric}
              aria-label={`Metric: ${name}. Change metric`}
              title={name}
              className="block w-full min-w-0 truncate text-left text-label text-ink-soft hover:text-ink"
            >
              {name}
            </button>
          )}
        </Tooltip>
        {flip ? (
          <button
            type="button"
            onClick={() => onChange(withComparator(cond, flip, unit))}
            aria-label={`Operator: ${CMP_LABEL[cond.cmp]}. Switch to ${CMP_LABEL[flip]}`}
            className="num inline-flex h-ctl w-7 items-center justify-center rounded-control border border-line-strong bg-paper text-label text-ink hover:border-ink-soft"
          >
            {CMP_LABEL[cond.cmp]}
          </button>
        ) : (
          <span />
        )}
        <span className="flex justify-end">
          {kind === "number" ? (
            <UnitInput unit={unit} value={typeof cond.value === "number" ? cond.value : null} onCommit={(v) => set({ value: v })} label={`${name} threshold`} width="w-10" />
          ) : (
            <button type="button" onClick={onToggleExpanded} className="w-full truncate text-right text-meta text-muted hover:text-ink" title={summary}>
              {complete ? summary.slice(name.length + 1) : "set…"}
            </button>
          )}
        </span>
        {!inGroup && (
          <span className="num text-right text-cell">
            {!complete || !step ? (
              <Tooltip tip={complete ? "Updating…" : "Not applied until it has a value."}>
                <span className="text-muted">—</span>
              </Tooltip>
            ) : (
              <span className={step.binding ? "font-semibold text-ink" : "text-ink-soft"} title={`${formatCount(step.remaining)} kept after this filter`}>
                {formatCount(step.remaining)}
              </span>
            )}
          </span>
        )}
        <IconButton label={`Remove filter: ${name}`} onClick={onRemove} className="opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100 sm:group-focus-within/row:opacity-100">
          <Icon name="close" />
        </IconButton>
      </div>
      {/* The sieve marks the stage that removes the most; the rail adds only when missing data is most of it. */}
      {!inGroup && step?.binding && step.removed_missing > step.removed / 2 && (
        <p className="pl-7 text-meta text-ink-soft">
          {formatCount(step.removed_missing)} of the {formatCount(step.removed)} removed have no {name}
        </p>
      )}
      {!complete && <p className="pl-7 text-meta text-caution">{hint ?? "Enter a value to apply this filter."}</p>}

      {expanded && (
        <div id={bodyId} className="space-y-2 pt-1 pb-2 pl-7">
          <div className="flex flex-wrap items-center gap-1.5">
            <select aria-label={`Comparator for ${name}`} value={cond.cmp} onChange={(e) => onChange(withComparator(cond, e.target.value as Comparator, unit))} className={SELECT}>
              {allowedComparators(unit).map((c) => (
                <option key={c} value={c}>
                  {CMP_WORDS[c]}
                </option>
              ))}
            </select>
            {kind !== "number" && <ValueFields cond={cond} unit={unit} kind={kind} name={name} sectors={sectors} set={set} />}
          </div>
          {numeric && dist && (
            <Histogram
              dist={dist}
              threshold={typeof cond.value === "number" ? cond.value : null}
              cmp={cond.cmp}
              unit={unit}
              label={`${name} distribution in the universe`}
              onThreshold={(v) => set({ value: v })}
              valueText={() => (step ? `${formatCount(step.remaining)} kept` : "")}
              caption={step && !inGroup ? <StepCaption step={step} /> : null}
            />
          )}
          {def && kind === "range" && dist && (
            <Histogram dist={dist} threshold={Array.isArray(cond.value) ? (cond.value as [number, number]) : null} cmp={cond.cmp} unit={unit} label={`${name} distribution in the universe`} />
          )}
          {def && (
            <Link href={metricHref(def.id)} className="inline-flex items-center gap-1 text-label text-forest underline underline-offset-2">
              <Icon name="info" />
              How {name} is computed
            </Link>
          )}
          {kind !== "none" && (
            <label className="flex items-center gap-2 text-label text-ink-soft">
              <input type="checkbox" checked={cond.missing === "pass"} onChange={(e) => set({ missing: e.target.checked ? "pass" : "fail" })} className="accent-forest" />
              Missing values pass
              {!inGroup && step && cond.missing !== "pass" && step.removed_missing > 0 && (
                <span className="num text-meta text-muted">(+{formatCount(step.removed_missing)})</span>
              )}
            </label>
          )}
        </div>
      )}
    </div>
  );
}


function StepCaption({ step }: { step: FunnelStep }): ReactNode {
  const failed = step.removed - step.removed_missing;
  return (
    <p className="num text-meta text-muted">
      {formatCount(step.remaining)} kept, {formatCount(failed)} failed, {formatCount(step.removed_missing)} had no data
    </p>
  );
}

export function ValueFields({
  cond,
  unit,
  kind,
  name,
  sectors,
  set,
}: {
  cond: Condition;
  unit: Unit;
  kind: ReturnType<typeof valueKind>;
  name: string;
  sectors: Sector[];
  set: (p: Partial<Condition>) => void;
}) {
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  switch (kind) {
    case "none":
      return null;
    case "number":
      return <UnitInput unit={unit} value={num(cond.value)} onCommit={(v) => set({ value: v })} label={`${name} threshold`} />;
    case "range": {
      const [lo, hi] = Array.isArray(cond.value) ? cond.value : [null, null];
      const both = (a: number | null, b: number | null) => set({ value: a === null && b === null ? null : [a as number, b as number] });
      return (
        <>
          <UnitInput unit={unit} value={num(lo)} onCommit={(v) => both(v, num(hi))} label={`${name} lower bound`} />
          <span className="text-meta text-muted">and</span>
          <UnitInput unit={unit} value={num(hi)} onCommit={(v) => both(num(lo), v)} label={`${name} upper bound`} />
        </>
      );
    }
    case "percentile":
      return (
        <>
          <UnitInput unit="frac" value={num(cond.value)} onCommit={(v) => set({ value: v })} label={`${name} percentile`} />
          <select aria-label="Percentile within" value={cond.within ?? "universe"} onChange={(e) => set({ within: e.target.value as "universe" | "sector" })} className={SELECT}>
            <option value="universe">of universe</option>
            <option value="sector">of its sector</option>
          </select>
        </>
      );
    case "vs_median": {
      const u = vsMedianUnit(unit);
      return (
        <>
          <UnitInput unit={u} value={num(cond.value)} onCommit={(v) => set({ value: v })} label={`${name} versus sector median`} />
        </>
      );
    }
    case "bool":
      return (
        <select aria-label={`${name} value`} value={String(cond.value ?? true)} onChange={(e) => set({ value: e.target.value === "true" })} className={SELECT}>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      );
    case "category":
      if (cond.cmp === "in") {
        const chosen = Array.isArray(cond.value) ? (cond.value as string[]) : [];
        return (
          <fieldset className="w-full">
            <legend className="sr-only">{name} values</legend>
            <div className="flex flex-wrap gap-1">
              {sectors.map((s) => {
                const on = chosen.includes(s);
                return (
                  <label key={s} className={`cursor-pointer rounded-full border px-2 py-0.5 text-meta ${on ? "border-forest bg-forest/10 text-forest" : "border-line-strong text-muted"}`}>
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={on}
                      onChange={() => {
                        const next = on ? chosen.filter((x) => x !== s) : [...chosen, s];
                        set({ value: next.length > 0 ? next : null });
                      }}
                    />
                    {s}
                  </label>
                );
              })}
            </div>
          </fieldset>
        );
      }
      return (
        <select aria-label={`${name} value`} value={typeof cond.value === "string" ? cond.value : ""} onChange={(e) => set({ value: e.target.value || null })} className={SELECT}>
          <option value="">Choose…</option>
          {sectors.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      );
  }
}

/** Why a value the user typed can't run yet, when there's a more specific reason than "empty". */
export function incompleteHint(cond: Condition, kind: ReturnType<typeof valueKind>): string | null {
  const v = cond.value;
  if (kind === "percentile" && typeof v === "number" && (v < 0 || v > 1)) return "Enter a percentile from 0 to 100.";
  if (kind === "range" && Array.isArray(v) && typeof v[0] === "number" && typeof v[1] === "number" && v[0] > v[1]) return "The lower bound is above the upper bound.";
  return null;
}

