"use client";

import { useRef, type KeyboardEvent, type PointerEvent, type ReactNode, memo, useMemo } from "react";
import { formatCount, formatValue, type Unit } from "@/lib/format";
import type { Distribution } from "@/lib/screen/engine";
import type { Comparator } from "@/lib/screen/types";
import { roundForInput } from "@/lib/units";

export type { Distribution };

/**
 * A filter's distribution with its threshold (docs/ui-spec.md §4.2).
 * - Bins are equal widths over p1–p99 of the universe; values beyond sit in labelled underflow and
 *   overflow bins, so an extreme outlier can't squash the chart into one spike.
 * - Kept bins are forest, removed bins a quiet neutral; a bin the threshold splits is drawn in two.
 * - "No data" is its own hatched bar.
 * - With `onThreshold`, the purple handle drags (snapping to bin edges), and ←/→ move it one bin
 *   (Shift: ten), Home/End to the ends.
 */
export const Histogram = memo(function Histogram({
  dist,
  threshold,
  cmp,
  unit,
  label,
  onThreshold,
  valueText,
  caption,
}: {
  dist: Distribution;
  threshold: number | [number, number] | null;
  cmp: Comparator;
  unit: Unit;
  label: string;
  onThreshold?: (v: number) => void;
  /** Spoken with the handle's value: "1,744 kept". */
  valueText?: (v: number) => string;
  caption?: ReactNode;
}) {
  const track = useRef<HTMLDivElement>(null);
  const { lo, hi, bins } = dist;
  const span = hi - lo || 1;
  const edges = [lo, ...bins.map((b) => b.hi)];
  const peak = Math.max(1, dist.underflow, dist.overflow, ...bins.map((b) => b.count));
  const single = typeof threshold === "number" ? threshold : null;
  // Bin labels depend only on the distribution: format them once, not on every drag step.
  const titles = useMemo(() => bins.map((b) => `${formatValue(unit, b.lo)} to ${formatValue(unit, b.hi)}: ${formatCount(b.count)} companies`), [bins, unit]);

  /** Share of the range [a, b] that passes (0..1). */
  const keptShare = (a: number, b: number): number => {
    if (threshold === null) return 0;
    const w = b - a || 1;
    if (Array.isArray(threshold)) return Math.max(0, Math.min(b, threshold[1]) - Math.max(a, threshold[0])) / w;
    if (cmp === "gte" || cmp === "gt") return Math.max(0, Math.min(1, (b - threshold) / w));
    if (cmp === "lte" || cmp === "lt") return Math.max(0, Math.min(1, (threshold - a) / w));
    return 0;
  };
  const underKept = keptShare(dist.min ?? lo, lo) >= 1 || (threshold !== null && !Array.isArray(threshold) && (cmp === "lte" || cmp === "lt") && threshold >= lo);
  const overKept = keptShare(hi, dist.max ?? hi) >= 1 || (threshold !== null && !Array.isArray(threshold) && (cmp === "gte" || cmp === "gt") && threshold <= hi);

  const pct = (v: number) => Math.max(0, Math.min(100, ((v - lo) / span) * 100));
  const snap = (v: number) => {
    let best = edges[0] as number;
    for (const e of edges) if (Math.abs(e - v) < Math.abs(best - v)) best = e;
    return roundForInput(unit, best);
  };
  const fromPointer = (e: PointerEvent) => {
    const r = track.current?.getBoundingClientRect();
    if (!r || !onThreshold) return;
    onThreshold(snap(lo + ((e.clientX - r.left) / r.width) * span));
  };
  const onKey = (e: KeyboardEvent) => {
    if (!onThreshold || single === null) return;
    const idx = edges.reduce((b, x, k) => (Math.abs(x - single) < Math.abs((edges[b] as number) - single) ? k : b), 0);
    const step = e.shiftKey ? 10 : 1;
    let next: number | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") next = edges[Math.min(edges.length - 1, idx + step)] as number;
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = edges[Math.max(0, idx - step)] as number;
    else if (e.key === "Home") next = lo;
    else if (e.key === "End") next = hi;
    if (next === null) return;
    e.preventDefault();
    onThreshold(roundForInput(unit, next));
  };

  const bar = (count: number, kept: number, key: string, title: string) => {
    const h = count > 0 ? Math.max(4, (count / peak) * 100) : 0;
    return (
      <div key={key} aria-hidden className="flex h-full flex-1 items-end" title={title}>
        <div className="flex w-full" style={{ height: `${h}%` }}>
          <div className="h-full bg-forest" style={{ width: `${kept * 100}%` }} />
          <div className="h-full flex-1 bg-line-strong/40" />
        </div>
      </div>
    );
  };
  const missingTotal = dist.missing + dist.notMeaningful;
  const range = `${formatValue(unit, lo)} to ${formatValue(unit, hi)}`;

  return (
    // The summary labels the figure (which may contain the slider); the bars themselves are hidden.
    <figure className="space-y-1" aria-label={`${label}. ${formatCount(dist.count)} with a value, ${range} between the 1st and 99th percentile; ${formatCount(missingTotal)} with no data.`}>
      <div className="flex h-12 items-end gap-1.5">
        {bar(dist.underflow, underKept ? 1 : 0, "under", `Below ${formatValue(unit, lo)}: ${formatCount(dist.underflow)} companies`)}
        <div ref={track} className="relative flex h-full flex-[10] items-end gap-px">
          {bins.map((b, k) => bar(b.count, keptShare(b.lo, b.hi), `b${k}`, titles[k] as string))}
          {Array.isArray(threshold) &&
            threshold.map((t, k) => <span key={k} aria-hidden className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-purple" style={{ left: `${pct(t)}%` }} />)}
          {single !== null && (
            <div
              role="slider"
              tabIndex={onThreshold ? 0 : -1}
              aria-label={`${label} threshold`}
              aria-valuemin={lo}
              aria-valuemax={hi}
              aria-valuenow={single}
              aria-valuetext={`${formatValue(unit, single)}${valueText ? `, ${valueText(single)}` : ""}`}
              aria-readonly={!onThreshold}
              onKeyDown={onKey}
              onPointerDown={(e) => {
                if (!onThreshold) return;
                e.currentTarget.setPointerCapture(e.pointerId);
                fromPointer(e);
              }}
              onPointerMove={(e) => {
                if (e.currentTarget.hasPointerCapture(e.pointerId)) fromPointer(e);
              }}
              className={`absolute inset-y-0 flex w-6 -translate-x-1/2 justify-center ${onThreshold ? "cursor-ew-resize touch-none" : ""}`}
              style={{ left: `${pct(single)}%` }}
            >
              <span aria-hidden className="h-full w-0.5 bg-purple" />
              <span aria-hidden className="absolute -top-1.5 size-3 rounded-full bg-purple shadow-[0_0_0_2px_var(--paper)]" />
            </div>
          )}
        </div>
        {bar(dist.overflow, overKept ? 1 : 0, "over", `Above ${formatValue(unit, hi)}: ${formatCount(dist.overflow)} companies`)}
        {missingTotal > 0 && (
          <div aria-hidden className="ml-2 flex h-full w-6 items-end" title={`No data: ${formatCount(dist.missing)} missing, ${formatCount(dist.notMeaningful)} not meaningful`}>
            <div className="hatch w-full" style={{ height: `${Math.max(4, Math.min(100, (missingTotal / peak) * 100))}%` }} />
          </div>
        )}
      </div>
      <div aria-hidden className="num flex justify-between text-meta text-muted">
        <span>≤ {formatValue(unit, lo)}</span>
        {missingTotal > 0 && <span className="ml-auto mr-2">No data: {formatCount(missingTotal)}</span>}
        <span>≥ {formatValue(unit, hi)}</span>
      </div>
      {caption}
    </figure>
  );
});
