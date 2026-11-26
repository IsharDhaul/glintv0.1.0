"use client";

import { memo, useId, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { FadeScroller } from "@/components/ui/FadeScroller";
import { Icon } from "@/components/ui/Icon";
import { MetricValue } from "@/components/ui/MetricValue";
import { NullValue } from "@/components/ui/NullValue";
import { InfoTip } from "@/components/ui/Tooltip";
import { formatCount } from "@/lib/format";
import { displayName } from "@/lib/names";
import { describeDistance, describeThreshold, gapOf, nearMissNote, nearMissUnit } from "@/lib/screen/nearMiss";
import type { MetricDefinition, NearMiss } from "@/lib/screen/types";

// The contract has NearMiss.note now; this only shows if the API sends a null value without one.
const NO_NOTE = "Missing value; no reason given.";

/** What "Include" would do for a near miss: the result count after relaxing its filter. */
export type Include = { count: number; current: number; apply: () => void };

/**
 * Near misses (docs/ui-spec.md §4.11): companies that pass the universe and fail exactly one
 * filter. Grouped by the filter they missed (in sieve order), each group sorted by the gap in
 * that metric's own units, so unlike units are never ranked against each other. "Include" moves
 * that filter's threshold just far enough and shows the new result count.
 */
export const NearMisses = memo(function NearMisses({
  items,
  enabled,
  onToggle,
  metrics,
  onOpen,
  labelFor,
  includeFor,
  defaultOpen = true,
}: {
  items: NearMiss[];
  /** screen.near_misses */
  enabled: boolean;
  onToggle: (on: boolean) => void;
  metrics: Map<string, MetricDefinition>;
  onOpen: (ticker: string) => void;
  /** Label for the failed filter, built from the screen (format.ts), not the API string. */
  labelFor: (m: NearMiss) => string;
  /** The Include action for a near miss, or null when relaxing can't include it. */
  includeFor?: (m: NearMiss) => Include | null;
  /** Collapsed on phones until opened (docs/ui-spec.md §2). */
  defaultOpen?: boolean;
}) {
  const [only, setOnly] = useState<string | null>(null);
  // null until toggled: follows defaultOpen (which can settle after the first render).
  const [openChoice, setOpen] = useState<boolean | null>(null);
  const open = openChoice ?? defaultOpen;
  const bodyId = useId();

  const groups = useMemo(() => {
    const by = new Map<string, NearMiss[]>();
    for (const m of items) {
      const key = m.failed_filter_path.join(".");
      const list = by.get(key);
      if (list) list.push(m);
      else by.set(key, [m]);
    }
    const stage = (key: string) => Number(key.split(".")[2] ?? 0);
    return [...by]
      .sort(([a], [b]) => stage(a) - stage(b))
      .map(([key, list]) => ({
        key,
        label: labelFor(list[0] as NearMiss),
        rows: [...list].sort((a, b) => {
          const ga = gapOf(a);
          const gb = gapOf(b);
          return Number(ga === null) - Number(gb === null) || (ga ?? 0) - (gb ?? 0) || (a.ticker < b.ticker ? -1 : 1);
        }),
      }));
  }, [items, labelFor]);
  const activeOnly = only && groups.some((g) => g.key === only) ? only : null;
  const shown = activeOnly ? groups.filter((g) => g.key === activeOnly) : groups;

  return (
    <section aria-labelledby="nm-h" className="rounded-panel bg-paper">
      <div className="flex flex-wrap items-center gap-2 px-panel py-2">
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)} className="flex items-center gap-1.5 text-left">
          <span aria-hidden className={`text-meta text-muted transition-transform duration-150 ${open ? "rotate-90" : ""}`}>
            <Icon name="chevron-right" />
          </span>
          <h2 id="nm-h" className="text-section font-semibold text-ink-soft">
            Near misses
          </h2>
          {enabled && <span className="num text-label text-muted">{formatCount(items.length)}</span>}
        </button>
        <InfoTip label="About near misses">Companies in the universe that fail exactly one filter, grouped by that filter, closest first.</InfoTip>
        <label className="ml-auto flex items-center gap-1.5 text-label text-ink-soft">
          <input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} className="accent-forest" />
          Compute near misses
        </label>
      </div>

      {open && (
        <div id={bodyId} className="border-t border-line">
          {!enabled ? (
            <p className="px-panel py-3 text-prose text-ink-soft">Near misses are off for this screen. Turn on Compute near misses to see companies that fail just one filter.</p>
          ) : items.length === 0 ? (
            <p className="px-panel py-3 text-prose text-ink-soft">No company fails just one filter: every company outside the results fails two or more.</p>
          ) : (
            <>
              {groups.length > 1 && (
                <FadeScroller role="group" aria-label="Show near misses for" className="flex gap-1 px-panel pt-2 pb-1 sm:flex-wrap">
                  <Chip pressed={activeOnly === null} onToggle={() => setOnly(null)}>
                    All, {formatCount(items.length)}
                  </Chip>
                  {groups.map((g) => (
                    <Chip key={g.key} pressed={activeOnly === g.key} onToggle={() => setOnly(g.key)}>
                      {g.label}, {formatCount(g.rows.length)}
                    </Chip>
                  ))}
                </FadeScroller>
              )}
              {shown.map((g) => (
                <div key={g.key} role="group" aria-label={`Missed ${g.label}`} className="pt-2">
                  <h3 className="px-panel text-label text-ink-soft">
                    Missed <span className="text-ink">{g.label}</span>, <span className="num">{formatCount(g.rows.length)}</span> {g.rows.length === 1 ? "company" : "companies"}
                  </h3>
                  <ul className="divide-y divide-line">
                    {g.rows.map((m) => (
                      <Row key={m.cik} m={m} metrics={metrics} onOpen={onOpen} include={includeFor?.(m) ?? null} />
                    ))}
                  </ul>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </section>
  );
});

function Row({ m, metrics, onOpen, include }: { m: NearMiss; metrics: Map<string, MetricDefinition>; onOpen: (t: string) => void; include: Include | null }) {
  const unit = nearMissUnit(m, metrics);
  const distance = describeDistance(m, metrics);
  return (
    <li className="grid grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-panel py-1.5 hover:bg-row-hover md:grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,14rem)_7rem_auto]">
      <button type="button" onClick={() => onOpen(m.ticker)} className="num justify-self-start rounded-control text-label font-semibold text-forest underline-offset-2 hover:underline" aria-label={`Open ${m.ticker}, ${m.name}`}>
        {m.ticker}
      </button>
      <span className="min-w-0 truncate text-label text-ink-soft" title={m.name}>
        {displayName(m.name)} <span className="ml-1 text-meta text-muted">{m.sector}</span>
      </span>
      <span className="num col-start-2 flex items-baseline gap-2 text-cell md:col-start-auto md:justify-end">
        <span className="font-medium text-ink">
          <span className="sr-only">value </span>
          {m.value === null ? <NullValue note={nearMissNote(m)} fallbackReason={NO_NOTE} /> : <MetricValue def={{ id: m.cmp.startsWith("pct_rank") ? "" : m.metric, unit }} value={m.value} note={null} />}
        </span>
        {(m.value !== null && m.note) || (m.threshold === null && m.cmp !== "is_null" && m.cmp !== "not_null") ? (
          // What the value was compared with is missing (small sector, median ≤ 0, or no threshold sent).
          <span className="text-muted">
            vs <NullValue note={m.note} fallbackReason="No threshold to compare with, and no reason given." />
          </span>
        ) : (
          <span className="text-muted">vs {describeThreshold(m, metrics)}</span>
        )}
      </span>
      <span className="num hidden text-right text-meta text-caution md:block">{distance}</span>
      <span className="col-start-3 row-start-1 justify-self-end md:col-start-auto md:row-start-auto">
        {include && (
          <Button onClick={include.apply} title="Move this filter's threshold just far enough to include this company">
            Include <span className="num text-muted">{include.count === include.current ? "(no change)" : `(${formatCount(include.count)})`}</span>
          </Button>
        )}
      </span>
    </li>
  );
}
