"use client";

import { memo, useMemo, useState } from "react";
import { Button, IconButton } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { MetricValue } from "@/components/ui/MetricValue";
import { NullValue } from "@/components/ui/NullValue";
import type { components } from "@/lib/api/types";
import { formatCount, formatGap, formatPercentilePoints, type Unit } from "@/lib/format";
import { noteAt } from "@/lib/data/snapshot";
import type { ScreenEngine } from "@/lib/screen/engine";
import { unitOf } from "@/lib/screen/filters";
import type { NodePath } from "@/lib/screen/filters";
import { relaxCondition } from "@/lib/screen/relax";
import { isGroup, type Condition, type MetricDefinition, type Screen } from "@/lib/screen/types";
import { updateAt } from "@/lib/screen/filters";

type FunnelStep = components["schemas"]["FunnelStep"];

const PAGE = 12;

/**
 * The companies one sieve stage removed (docs/ui-spec.md §4.3): closest to passing first, each
 * with its value and how far off it was, and "Include" to move the threshold just far enough
 * (with the new result count). Companies removed for missing data can't be included by a
 * threshold; they offer "Let missing values pass" instead.
 */
export const RemovedPanel = memo(function RemovedPanel({
  engine,
  screen,
  step,
  label,
  metrics,
  onChange,
  onEdit,
  onClose,
}: {
  engine: ScreenEngine | null;
  /** The screen as it runs (complete filters only). */
  screen: Screen;
  step: FunnelStep;
  label: string;
  metrics: Map<string, MetricDefinition>;
  /** Replace the top-level filter at `path`. */
  onChange: (path: NodePath, c: Condition) => void;
  onEdit: () => void;
  onClose: () => void;
}) {
  const [limit, setLimit] = useState(PAGE);
  const node = screen.filters?.children?.[step.index - 1];
  const top = node && !isGroup(node) ? node : null;
  const path: NodePath = { top: step.index - 1 };
  const rows = useMemo(() => (engine ? engine.removedAt(screen, step.index, limit) : []), [engine, screen, step.index, limit]);
  const final = screen.filters?.children?.length ?? 0;
  const current = engine ? (engine.evaluate(screen, { nearMisses: false, rank: false }).funnel[final]?.remaining ?? null) : null;

  /** The result count if this condition replaced the stage's. */
  const preview = (c: Condition) => {
    if (!engine) return null;
    const next = updateAt(screen, path, c);
    return engine.evaluate(next, { nearMisses: false, rank: false }).funnel[final]?.remaining ?? null;
  };

  return (
    <section aria-label={`Companies removed by ${label}`} className="space-y-2 rounded-panel bg-paper p-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-section font-semibold text-ink-soft">Removed by {label}</h3>
        <span className="num text-label text-muted">
          {formatCount(step.removed)}
          {step.removed_missing > 0 ? `, ${formatCount(step.removed_missing)} with no data` : ""}
        </span>
        <span className="ml-auto flex items-center gap-1">
          <Button variant="ghost" onClick={onEdit}>
            Edit this filter
          </Button>
          <IconButton label="Close the removed list" onClick={onClose}>
            <Icon name="close" />
          </IconButton>
        </span>
      </div>
      {top && step.removed_missing > 0 && top.missing !== "pass" && (
        <p className="flex flex-wrap items-center gap-2 text-label text-ink-soft">
          <span className="hatch inline-block h-3 w-4 rounded-control" aria-hidden />
          <span className="num">{formatCount(step.removed_missing)}</span> had no {metrics.get(top.metric)?.name ?? top.metric}. A lower threshold can&apos;t bring them back.
          <Button variant="ghost" onClick={() => onChange(path, { ...top, missing: "pass" })}>
            Let missing values pass
          </Button>
        </p>
      )}
      {!engine ? (
        <p className="text-prose text-ink-soft">Loading this build&apos;s data to list them…</p>
      ) : rows.length === 0 ? (
        <p className="text-prose text-ink-soft">This filter didn&apos;t remove anyone.</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((r) => {
            const unit: Unit = unitOf(r.cond.metric, metrics);
            const def = metrics.get(r.cond.metric) ?? { id: r.cond.metric, unit };
            const relaxed = top && r.reason === "failed" ? relaxCondition(top, r.value, r.compared, unit) : null;
            const gap =
              r.reason === "failed" && typeof r.value === "number" && typeof top?.value === "number"
                ? top.cmp.startsWith("pct_rank")
                  ? r.compared !== null
                    ? `${formatPercentilePoints(Math.abs(r.compared - top.value))} off`
                    : null
                  : `${formatGap(unit, Math.abs(r.value - top.value))} off`
                : null;
            const count = relaxed ? preview(relaxed) : null;
            return (
              <li key={r.row} className="grid grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-1.5 sm:grid-cols-[4.5rem_minmax(0,1fr)_7rem_7rem_auto]">
                <span className="num text-label font-semibold text-forest">{r.ticker}</span>
                <span className="truncate text-label text-ink-soft">{r.name}</span>
                <span className="num text-right text-cell text-ink">
                  {r.value === null ? (
                    <NullValue note={(() => { const code = noteAt(engine.store, r.cond.metric, r.row); return code ? { code, message: "" } : null; })()} fallbackReason="No value in this build." />
                  ) : (
                    <MetricValue def={def} value={r.value} note={null} />
                  )}
                </span>
                <span className="num hidden text-right text-meta text-caution sm:block">{gap ?? (r.reason === "no_data" ? <span className="text-muted">no data</span> : "")}</span>
                <span className="justify-self-end">
                  {relaxed && count !== null ? (
                    <Button onClick={() => onChange(path, relaxed)} title={`Move the threshold just far enough to let ${r.ticker} through this filter`}>
                      Include{" "}
                      <span className="num text-muted">{count === current ? "(no change in results)" : `(${formatCount(count)} results)`}</span>
                    </Button>
                  ) : r.reason === "no_data" && top && top.missing !== "pass" ? (
                    <Button variant="ghost" onClick={() => onChange(path, { ...top, missing: "pass" })}>
                      Let missing values pass
                    </Button>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {engine && rows.length >= limit && limit < step.removed && (
        <Button variant="ghost" onClick={() => setLimit((l) => l + PAGE * 2)}>
          Show more
        </Button>
      )}
    </section>
  );
});
