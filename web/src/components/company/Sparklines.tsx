"use client";

import { Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { components } from "@/lib/api/types";
import { formatDate, formatMetric } from "@/lib/format";
import type { MetricDefinition } from "@/lib/screen/types";

type HistoryPoint = components["schemas"]["HistoryPoint"];
type Def = { id: string; name: string; unit: MetricDefinition["unit"] };
type Pt = { t: number; value: number | null; basis: "fy" | "ttm"; period_end: string };

// Recharts lives here only: the drawer and company page load this lazily, and table rows never
// render charts. Animation is off, so reduced motion needs nothing extra.

/**
 * History (docs/ui-spec.md §4.8): one chart per metric, fiscal years (forest, with dots) and
 * trailing twelve months (soft line) on one shared axis. A dashed zero line when the range
 * crosses zero (always for margins), start and end labels, a crosshair with the period and value
 * (←/→ when focused), and missing periods drawn as hatched gaps.
 */
export default function Sparklines({ history, metrics }: { history: Record<string, HistoryPoint[]>; metrics: Map<string, MetricDefinition> }) {
  const ids = Object.keys(history).filter((id) => (history[id]?.length ?? 0) > 0);
  if (ids.length === 0) return <p className="text-prose text-ink-soft">This build keeps no history for this company.</p>;
  return (
    <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
      {ids.map((id) => (
        <Chart key={id} def={metrics.get(id) ?? { id, name: id, unit: "score" }} points={history[id] ?? []} />
      ))}
    </div>
  );
}

const periodLabel = (p: { basis: "fy" | "ttm"; period_end: string }) =>
  p.basis === "fy" ? `FY${p.period_end.slice(0, 4)}` : `TTM to ${formatDate(p.period_end).slice(0, 7)}`;

function Chart({ def, points }: { def: Def; points: HistoryPoint[] }) {
  const pts: Pt[] = points.map((p) => ({ ...p, t: Date.parse(`${p.period_end}T00:00:00Z`) }));
  const fy = pts.filter((p) => p.basis === "fy").sort((a, b) => a.t - b.t);
  const ttm = pts.filter((p) => p.basis === "ttm").sort((a, b) => a.t - b.t);
  const present = pts.filter((p) => p.value !== null);
  const values = present.map((p) => p.value as number);
  const margin = /margin/.test(def.id);
  const lo = Math.min(...values, margin ? 0 : Infinity);
  const hi = Math.max(...values, margin ? 0 : -Infinity);
  const crossesZero = lo <= 0 && hi >= 0;
  const first = fy.find((p) => p.value !== null) ?? ttm.find((p) => p.value !== null);
  const last = [...ttm].reverse().find((p) => p.value !== null) ?? [...fy].reverse().find((p) => p.value !== null);
  const fmt = (v: number) => formatMetric(def, v);
  // Missing periods: a hatched band from the previous to the next present point of that series.
  const gaps = [fy, ttm].flatMap((series) =>
    series.flatMap((p, i) => {
      if (p.value !== null) return [];
      const prev = series[i - 1]?.t ?? p.t;
      const next = series[i + 1]?.t ?? p.t;
      return [{ x1: prev, x2: next, label: periodLabel(p) }];
    }),
  );
  const missing = pts.length - present.length;
  const summary =
    first && last
      ? `${def.name}: ${fmt(first.value as number)} (${periodLabel(first)}) to ${fmt(last.value as number)} (${periodLabel(last)}), ${pts.length} points${missing ? `, ${missing} missing` : ""}.`
      : `${def.name}: no values in this build.`;
  const patternId = `gap-${def.id}`;

  return (
    <figure aria-label={summary} className="space-y-1">
      <figcaption className="flex items-baseline justify-between gap-2">
        <span className="text-label font-semibold text-ink-soft">{def.name}</span>
        <span aria-hidden className="flex items-center gap-3 text-meta text-muted">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block size-1.5 rounded-full bg-forest" />
            FY
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block h-0.5 w-3 bg-ink-soft" />
            TTM
          </span>
        </span>
      </figcaption>
      {present.length > 1 ? (
        <div className="h-16">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }} accessibilityLayer>
              <defs>
                <pattern id={patternId} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <rect width="2" height="5" fill="var(--nodata)" opacity="0.45" />
                </pattern>
              </defs>
              <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide allowDuplicatedCategory={false} />
              <YAxis hide domain={[lo, hi]} />
              {crossesZero && <ReferenceLine y={0} stroke="var(--line-strong)" strokeDasharray="3 3" />}
              {gaps.map((g, i) => (
                <ReferenceArea key={i} x1={g.x1} x2={g.x2} fill={`url(#${patternId})`} fillOpacity={1} ifOverflow="extendDomain" />
              ))}
              <Line data={ttm} dataKey="value" name="TTM" stroke="var(--ink-soft)" strokeWidth={1.5} dot={false} connectNulls={false} isAnimationActive={false} />
              <Line data={fy} dataKey="value" name="FY" stroke="var(--forest)" strokeWidth={1.75} dot={{ r: 2, fill: "var(--forest)", strokeWidth: 0 }} connectNulls={false} isAnimationActive={false} />
              <Tooltip
                cursor={{ stroke: "var(--line-strong)" }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  return (
                    <div className="num rounded-panel bg-paper px-2 py-1 text-meta text-ink-soft shadow-overlay">
                      {payload.map((e) => {
                        const p = e.payload as Pt;
                        return (
                          <div key={`${p.basis}-${p.t}`}>
                            {periodLabel(p)}: {p.value === null ? "no value in this build" : fmt(p.value)}
                          </div>
                        );
                      })}
                    </div>
                  );
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="flex h-16 items-center text-meta text-muted">Not enough history to draw.</p>
      )}
      {first && last && (
        <p aria-hidden className="num flex justify-between text-meta text-muted">
          <span>
            {periodLabel(first)} <span className="text-ink-soft">{fmt(first.value as number)}</span>
          </span>
          <span>
            {periodLabel(last)} <span className="font-medium text-ink">{fmt(last.value as number)}</span>
          </span>
        </p>
      )}
    </figure>
  );
}
