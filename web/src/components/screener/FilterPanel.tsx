"use client";

import { Icon } from "@/components/ui/Icon";
import { useCallback, useState } from "react";
import { Button, IconButton } from "@/components/ui/Button";
import type { Distribution } from "@/components/ui/Histogram";
import { InfoTip } from "@/components/ui/Tooltip";
import type { components } from "@/lib/api/types";
import { formatCount, formatValue } from "@/lib/format";
import type { NodePath } from "@/lib/screen/filters";
import { isGroup, type Condition, type MetricDefinition, type Screen, type Sector } from "@/lib/screen/types";
import { FilterRow } from "./FilterRow";

type FunnelStep = components["schemas"]["FunnelStep"];

/** Where the metric picker's choice goes. */
export type PickTarget = { mode: "add" } | { mode: "new_or" } | { mode: "add_to_group"; top: number } | { mode: "replace"; path: NodePath };

const key = (p: NodePath) => (p.child === undefined ? `${p.top}` : `${p.top}.${p.child}`);

/**
 * The filter rail (docs/ui-spec.md §4.1): one line per filter, in sieve order, each expandable
 * to its histogram; OR groups as indented lines under "Any of". Then the ranking.
 */
export function FilterPanel({
  screen,
  metrics,
  sectors,
  steps,
  dist,
  highlight,
  onUpdate,
  onRemove,
  onPick,
}: {
  screen: Screen;
  metrics: Map<string, MetricDefinition>;
  sectors: Sector[];
  /** Funnel step per top-level filter (null if the filter is incomplete or hasn't run). */
  steps: (FunnelStep | null)[];
  /** A metric's distribution over the current universe (null until the column data loads). */
  dist: (metric: string) => Distribution | null;
  highlight: number | null;
  onUpdate: (path: NodePath, c: Condition) => void;
  onRemove: (path: NodePath) => void;
  onPick: (target: PickTarget) => void;
}) {
  const top = screen.filters?.children ?? [];
  // A filter just added opens expanded, so its histogram is right there; others start collapsed.
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [seen, setSeen] = useState(top.length);
  if (top.length !== seen) {
    if (top.length === seen + 1) setOpen((o) => new Set(o).add(`${top.length - 1}`));
    setSeen(top.length);
  }
  const toggle = useCallback(
    (p: NodePath) =>
      setOpen((o) => {
        const next = new Set(o);
        if (next.has(key(p))) next.delete(key(p));
        else next.add(key(p));
        return next;
      }),
    [],
  );

  return (
    <div className="space-y-6">
      <section aria-labelledby="filters-h" className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <h2 id="filters-h" className="text-section font-semibold text-ink-soft">
              Filters
            </h2>
            <InfoTip label="About filters">
              {screen.filters?.op === "or"
                ? "A company is kept if it passes any one filter."
                : "A company is kept only if it passes every filter, in this order. The number on each line is how many are left after it."}
            </InfoTip>
          </div>
          <div className="flex gap-1">
            <Button onClick={() => onPick({ mode: "new_or" })} title="Add a group where any one condition passes">
              Add OR group
            </Button>
            <Button onClick={() => onPick({ mode: "add" })} aria-keyshortcuts="f" data-add-filter>
              Add filter
            </Button>
          </div>
        </div>
        {top.length === 0 ? (
          <div className="space-y-2 rounded-panel bg-paper p-panel">
            <p className="text-prose text-ink-soft">Add a filter to start narrowing the universe.</p>
            <p className="text-meta text-muted">
              Or pick a preset. Press <kbd className="font-code">f</kbd> to add a filter, <kbd className="font-code">/</kbd> to search.
            </p>
          </div>
        ) : (
          <ol className="divide-y divide-line rounded-panel bg-paper px-2">
            {top.map((node, i) => {
              const step = steps[i] ?? null;
              const lit = highlight === i;
              return (
                <li key={i} id={`filter-${i}`} tabIndex={-1} className={`scroll-mt-32 transition-shadow duration-200 ${lit ? "shadow-[inset_3px_0_0_var(--purple)]" : ""}`}>
                  {isGroup(node) ? (
                    <div className="py-1">
                      <div className="flex min-h-ctl items-center gap-1.5">
                        <span className="pl-7 text-label text-ink-soft">Any of</span>
                        <span className="num ml-auto w-12 text-right text-cell">
                          {step ? <span className={step.binding ? "font-semibold text-ink" : "text-ink-soft"}>{formatCount(step.remaining)}</span> : <span className="text-muted">—</span>}
                        </span>
                        <IconButton label="Remove this group" onClick={() => onRemove({ top: i })}>
                          <Icon name="close" />
                        </IconButton>
                      </div>
                      {step?.binding && <p className="pl-7 text-meta text-ink">removes the most</p>}
                      <ul className="ml-7 border-l border-line pl-2">
                        {(node.children ?? []).map((ch, j) =>
                          isGroup(ch) ? (
                            <li key={j} className="py-1 text-meta text-muted">
                              A nested group (only one level can be edited here).
                            </li>
                          ) : (
                            <li key={j}>
                              <FilterRow
                                inGroup
                                cond={ch}
                                metrics={metrics}
                                sectors={sectors}
                                step={null}
                                dist={dist(ch.metric)}
                                path={{ top: i, child: j }}
                                expanded={open.has(key({ top: i, child: j }))}
                                onToggle={toggle}
                                onUpdate={onUpdate}
                                onRemovePath={onRemove}
                                onPick={onPick}
                              />
                            </li>
                          ),
                        )}
                        <li>
                          <Button variant="ghost" onClick={() => onPick({ mode: "add_to_group", top: i })}>
                            Add to this group
                          </Button>
                        </li>
                      </ul>
                    </div>
                  ) : (
                    <FilterRow
                      cond={node}
                      metrics={metrics}
                      sectors={sectors}
                      step={step}
                      dist={dist(node.metric)}
                      path={{ top: i }}
                      expanded={open.has(key({ top: i }))}
                      onToggle={toggle}
                      onUpdate={onUpdate}
                      onRemovePath={onRemove}
                      onPick={onPick}
                    />
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {screen.rank && (
        <section aria-labelledby="rank-h" className="space-y-2">
          <h2 id="rank-h" className="text-section font-semibold text-ink-soft">
            Ranked by
          </h2>
          <div className="space-y-1 rounded-panel bg-paper p-panel text-label">
            {screen.rank.factors.map((f) => (
              <div key={f.metric} className="flex justify-between gap-2">
                <span className="text-ink-soft">{metrics.get(f.metric)?.name ?? f.metric}</span>
                <span className="num text-muted">{formatValue("frac", f.weight / (screen.rank?.factors.reduce((s, x) => s + x.weight, 0) || 1))}</span>
              </div>
            ))}
            <p className="pt-1 text-meta text-muted">
              {screen.rank.method === "rank_sum" ? "Sum of ranks" : "Average percentile"}, within {screen.rank.within === "sector" ? "each sector" : "the universe"}.
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
