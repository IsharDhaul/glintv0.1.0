"use client";

import { ApiError } from "@/lib/api/client";
import { useCompany, useDistribution, useMeta, useMetrics, usePreset, usePresets, useScreen, useSearch, useSectors } from "@/lib/api/hooks";

// Dev page for the data layer (WT-05 step 2): every hook's state in one place.
// Try ?mock=down, ?mock=nobuild, ?mock=empty, ?mock=slow, then ?mock=ok.

function Row({ name, q, summary }: { name: string; q: { isPending: boolean; error: unknown; data?: unknown }; summary: (d: never) => string }) {
  const err = q.error instanceof ApiError ? `${q.error.kind}: ${q.error.message}` : q.error ? String(q.error) : null;
  return (
    <tr className="h-row border-t border-line" data-testid={`hook-${name}`}>
      <th scope="row" className="px-cell text-left num font-semibold text-forest">
        {name}
      </th>
      <td className="px-cell">
        {err ? <span className="text-neg">{err}</span> : q.isPending ? <span className="text-muted">loading…</span> : summary(q.data as never)}
      </td>
    </tr>
  );
}

export default function DataPage() {
  const meta = useMeta();
  const metrics = useMetrics();
  const sectors = useSectors();
  const presets = usePresets();
  const preset = usePreset("quality-compounders");
  const screen = useScreen(preset.data?.preset.screen ?? null);
  const dist = useDistribution("roic");
  const search = useSearch("SYN00");
  const company = useCompany(screen.data?.results[0]?.ticker ?? null);

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-6">
      <h1 className="text-title font-semibold text-ink">Data layer</h1>
      <table className="w-full text-label">
        <tbody>
          <Row name="meta" q={meta} summary={(d: NonNullable<typeof meta.data>) => `build ${d.build_id}, synthetic=${String(d.synthetic)}`} />
          <Row name="metrics" q={metrics} summary={(d: NonNullable<typeof metrics.data>) => `${d.metrics.length} metrics`} />
          <Row name="sectors" q={sectors} summary={(d: NonNullable<typeof sectors.data>) => d.sectors.map((s) => s.sector).join(", ")} />
          <Row name="presets" q={presets} summary={(d: NonNullable<typeof presets.data>) => d.presets.map((p) => p.id).join(", ")} />
          <Row
            name="screen"
            q={screen}
            summary={(d: NonNullable<typeof screen.data>) =>
              `${d.results.length} rows · funnel: ${d.funnel.map((s) => s.label).join(" → ")} · ${d.warnings.join(" ")}`
            }
          />
          <Row name="distribution" q={dist} summary={(d: NonNullable<typeof dist.data>) => `${d.bins.length} bins, ${d.count} values`} />
          <Row name="search" q={search} summary={(d: NonNullable<typeof search.data>) => d.results.slice(0, 5).map((h) => h.ticker).join(", ")} />
          <Row name="company" q={company} summary={(d: NonNullable<typeof company.data>) => `${d.company.name} · ${Object.keys(d.history).join(", ")}`} />
        </tbody>
      </table>
    </main>
  );
}
