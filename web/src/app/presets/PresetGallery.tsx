"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { isRedFlagPreset } from "@/components/company/RedFlags";
import { StatusBanner } from "@/components/screener/StatusBanner";
import { Icon } from "@/components/ui/Icon";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys, useMetrics, usePresets, useSnapshot } from "@/lib/api/hooks";
import type { components } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { encodeScreen } from "@/lib/screen/codec";
import { describeNode, metricMap } from "@/lib/screen/describe";
import { ScreenEngine } from "@/lib/screen/engine";
import { DEFAULT_UNIVERSE, universeChips } from "@/lib/screen/universe";
import type { MetricDefinition } from "@/lib/screen/types";

type Preset = components["schemas"]["Preset"];

// The default universe's rules: cards list only what a preset changes from them.
const DEFAULT_RULES = universeChips(DEFAULT_UNIVERSE).map((c) => c.label);

/** A rule label set inside a sentence: "Listed on NYSE…" → "listed on NYSE…"; "US companies…" stays. */
const inSentence = (label: string) => (/^[A-Z][a-z]/.test(label) ? label.charAt(0).toLowerCase() + label.slice(1) : label);

/**
 * Preset gallery (docs/glint-ui-upgrade.md Phase 4.10). Each card is one link to the screener: its
 * name, what it looks for, how many companies pass in this build (the browser engine over the
 * build's columns), and what to keep in mind, which is where each preset says what it misses.
 * Red-flag screens sit in their own group, since they're checks to run, not lists to browse.
 */
export function PresetGallery() {
  const list = usePresets();
  const metrics = useMetrics();
  const snapshot = useSnapshot();
  const defs = useMemo(() => metricMap(metrics.data?.metrics ?? []), [metrics.data]);
  const engine = useMemo(() => (snapshot.data && metrics.data ? new ScreenEngine(snapshot.data, defs) : null), [snapshot.data, metrics.data, defs]);
  const details = useQueries({
    queries: (list.data?.presets ?? []).map((p) => ({
      queryKey: queryKeys.preset(p.id),
      queryFn: () => unwrap(api.GET("/api/presets/{preset_id}", { params: { path: { preset_id: p.id } } })),
      staleTime: Infinity,
    })),
  });
  const summaries = list.data?.presets ?? [];
  const groups = [
    { id: "screens", title: "Screens", note: null, items: summaries.map((p, i) => ({ p, i })).filter(({ p }) => !isRedFlagPreset(p.name)) },
    {
      id: "risk",
      title: "Risk checks",
      note: "Red-flag screens. Run candidates against them: each match is a question worth looking into. The company page shows which ones a company matches.",
      items: summaries.map((p, i) => ({ p, i })).filter(({ p }) => isRedFlagPreset(p.name)),
    },
  ].filter((g) => g.items.length > 0);

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <header className="space-y-1">
        <h1 className="text-title font-semibold text-ink">Presets</h1>
        <p className="max-w-3xl text-prose text-ink-soft">
          Starting points from published screens and common heuristics. Open one to adjust its thresholds.
        </p>
        <p className="max-w-3xl text-label text-muted">
          Every preset screens the default universe ({DEFAULT_RULES.map(inSentence).join(", ")}) unless its card says otherwise.
        </p>
      </header>

      <StatusBanner error={list.error ?? metrics.error} />

      {list.isPending ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading presets">
          {Array.from({ length: 3 }, (_, k) => (
            <div key={k} className="h-64 animate-pulse rounded-panel bg-dune" />
          ))}
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.id} aria-labelledby={`g-${g.id}`} className="space-y-2">
            <div className="flex items-baseline gap-2">
              <h2 id={`g-${g.id}`} className="text-section font-semibold text-ink-soft">
                {g.title}
              </h2>
              <span className="num text-meta text-muted">{formatCount(g.items.length)}</span>
            </div>
            {g.note && <p className="max-w-3xl text-label text-ink-soft">{g.note}</p>}
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {g.items.map(({ p, i }) => {
                const preset = details[i]?.data?.preset;
                return (
                  <li key={p.id}>
                    {preset ? (
                      <PresetCard preset={preset} defs={defs} engine={engine} risk={g.id === "risk"} />
                    ) : (
                      <div className="h-64 animate-pulse rounded-panel bg-dune" role="status" aria-label={`Loading ${p.name}`} />
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </main>
  );
}

function PresetCard({ preset, defs, engine, risk }: { preset: Preset; defs: Map<string, MetricDefinition>; engine: ScreenEngine | null; risk: boolean }) {
  const s = preset.screen;
  const filters = s.filters?.children ?? [];
  const narrowing = universeChips(s.universe).filter((c) => !DEFAULT_RULES.includes(c.label));
  const [more, setMore] = useState(false);
  const count = useMemo(() => {
    if (!engine) return null;
    const funnel = engine.evaluate(s, { nearMisses: false, rank: false }).funnel;
    return funnel[funnel.length - 1]?.remaining ?? null;
  }, [engine, s]);
  const name = risk ? preset.name.replace(/\s*\(red flags\)\s*$/i, "") : preset.name;
  const id = `p-${preset.id}`;

  return (
    // The title's link stretches over the whole card (after:inset-0); the one other control sits above it.
    <article
      aria-labelledby={id}
      className="group relative flex h-full flex-col gap-3 rounded-panel bg-paper p-panel transition-colors duration-150 ease-out hover:bg-dune/50 has-[a:focus-visible]:shadow-[var(--focus-ring)]"
    >
      <div className="space-y-1">
        <h3 id={id} className="text-prose font-semibold text-ink">
          <Link href={`/?s=${encodeScreen(s)}`} className="after:absolute after:inset-0 after:rounded-panel focus-visible:shadow-none" aria-label={`Open ${preset.name} in the screener`}>
            {name}
          </Link>
        </h3>
        <p className="text-label text-ink-soft">{preset.summary}</p>
      </div>

      <p className="text-label text-ink-soft" aria-live="polite">
        {count === null ? (
          <span className="text-muted">Counting…</span>
        ) : filters.length === 0 ? (
          <>
            Ranks <span className="num font-semibold text-ink">{formatCount(count)}</span> {count === 1 ? "company" : "companies"} in this build
          </>
        ) : (
          <>
            <span className="num font-semibold text-ink">{formatCount(count)}</span> {count === 1 ? "company matches" : "companies match"} in this build
          </>
        )}
      </p>

      <div className="space-y-1">
        <h4 className="text-label font-medium text-muted">Looks for</h4>
        {filters.length === 0 ? (
          <p className="text-label text-ink-soft">No filters: a ranking of the whole universe.</p>
        ) : (
          <ul className="space-y-0.5 text-label text-ink-soft">
            {filters.map((f, i) => (
              <li key={i} className="flex gap-1.5">
                <span aria-hidden className="mt-2 inline-block size-1 shrink-0 rounded-full bg-forest" />
                <span>{describeNode(f, defs)}</span>
              </li>
            ))}
          </ul>
        )}
        {s.rank && (
          <p className="text-label text-ink-soft">
            Ranked by {s.rank.factors.map((f) => defs.get(f.metric)?.name ?? f.metric).join(" and ")}, {s.rank.method === "rank_sum" ? "sum of ranks" : "average percentile"}{" "}
            within the {s.rank.within}.
          </p>
        )}
        {narrowing.length > 0 && <p className="text-label text-ink-soft">Also limits the universe: {narrowing.map((c) => inSentence(c.label)).join(", ")}.</p>}
      </div>

      <div className="space-y-1">
        <h4 className="text-label font-medium text-muted">Keep in mind</h4>
        <p id={`${id}-read`} className={`text-label text-ink-soft ${more ? "" : "line-clamp-3"}`}>
          {preset.how_to_read}
        </p>
        <button
          type="button"
          onClick={() => setMore((m) => !m)}
          aria-expanded={more}
          aria-controls={`${id}-read`}
          className="relative z-10 rounded-control text-label text-forest underline underline-offset-2"
        >
          {more ? "Show less" : "Read more"}
        </button>
        {preset.misses && preset.misses.length > 0 && (
          <>
            <h4 className="pt-1 text-label font-medium text-muted">What it misses</h4>
            <ul className="list-disc space-y-0.5 pl-4 text-label text-ink-soft">
              {preset.misses.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      <p className="mt-auto text-meta text-muted">Source: {preset.source}</p>
      <span aria-hidden className="inline-flex items-center gap-1 text-label font-medium text-forest">
        Open in the screener
        <Icon name="chevron-right" className="transition-transform duration-150 ease-out group-hover:translate-x-0.5" />
      </span>
    </article>
  );
}
