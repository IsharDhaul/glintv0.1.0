"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { CompanyView } from "@/components/company/CompanyView";
import { RedFlags } from "@/components/company/RedFlags";
import { Icon } from "@/components/ui/Icon";
import { StatusBanner } from "@/components/screener/StatusBanner";
import { useCompany, useMetrics, useSnapshot } from "@/lib/api/hooks";
import { decodeScreen } from "@/lib/screen/codec";
import { metricMap } from "@/lib/screen/describe";
import { ScreenEngine } from "@/lib/screen/engine";
import { isGroup, type Condition, type Group } from "@/lib/screen/types";

/**
 * Full-page company view (docs/ui-spec.md §4.8). `?s=` carries the screen it was opened from.
 * The build's columns (shared with the screener's cache) give each metric its sector median and
 * percentile, and the red-flag presets this company trips.
 */
export function CompanyPage({ ticker }: { ticker: string }) {
  const params = useSearchParams();
  const sParam = params.get("s");
  const screen = useMemo(() => decodeScreen(sParam), [sParam]);
  const company = useCompany(ticker, screen);
  const metrics = useMetrics();
  const snapshot = useSnapshot();
  const err = company.error ?? metrics.error;

  const defs = useMemo(() => metricMap(metrics.data?.metrics ?? []), [metrics.data]);
  const engine = useMemo(() => (snapshot.data && metrics.data ? new ScreenEngine(snapshot.data, defs) : null), [snapshot.data, metrics.data, defs]);
  const row = company.data && engine ? (engine.store.index.get(company.data.company.cik) ?? null) : null;
  const universe = screen?.universe;
  const stats = useMemo(
    () =>
      engine && row !== null
        ? (metric: string) => ({ median: engine.sectorMedianOf(universe, metric, row), percentile: engine.sectorPercentile(universe, metric, row) })
        : undefined,
    [engine, row, universe],
  );
  const screened = useMemo(() => {
    const ids = new Set<string>();
    const walk = (n: Condition | Group) => (isGroup(n) ? (n.children ?? []).forEach(walk) : ids.add(n.metric));
    (screen?.filters?.children ?? []).forEach(walk);
    for (const f of screen?.rank?.factors ?? []) ids.add(f.metric);
    return ids;
  }, [screen]);

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <Link href={screen ? `/?s=${sParam}` : "/"} className="inline-flex items-center gap-1 text-label text-forest underline underline-offset-2">
        <Icon name="chevron-right" className="rotate-180" />
        Back to {screen ? screen.name : "the screener"}
      </Link>
      {err ? (
        <StatusBanner error={err} />
      ) : !company.data || !metrics.data ? (
        <div className="space-y-2" role="status" aria-label="Loading company">
          {Array.from({ length: 8 }, (_, k) => (
            <div key={k} className="h-6 animate-pulse rounded-panel bg-dune" />
          ))}
        </div>
      ) : (
        <CompanyView
          data={company.data}
          metrics={metrics.data.metrics}
          screen={screen}
          variant="page"
          stats={stats}
          screened={screened}
          extraFlags={<RedFlags engine={engine} row={row} defs={defs} />}
        />
      )}
    </main>
  );
}
