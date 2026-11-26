"use client";

import { Icon } from "@/components/ui/Icon";
import { useQueryClient } from "@tanstack/react-query";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useStableCallback } from "@/lib/useStableCallback";
import { SieveBar } from "@/components/ui/SieveBar";
import { api, unwrap } from "@/lib/api/client";
import { exportScreen, queryKeys, useMeta, useMetrics, usePresets, useScreen, useSectors, useSnapshot } from "@/lib/api/hooks";
import { ScreenEngine } from "@/lib/screen/engine";
import { liveResponse, sameAnswer } from "@/lib/screen/live";
import type { components } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { nextSort, responseBadges, responseColumns, setColumns, userColumns, withBadgeColumns, withMetricColumn } from "@/lib/screen/columns";
import { effectiveUniverse } from "@/lib/screen/defaults";
import { metricMap } from "@/lib/screen/describe";
import { addFilter, addOrGroup, getAt, newCondition, removeAt, runnable, unitOf, updateAt, type NodePath } from "@/lib/screen/filters";
import { isGroup, type Condition, type Group, type MetricDefinition, type Screen } from "@/lib/screen/types";
import { stepLabel } from "@/lib/screen/funnel";
import { MAX_PINNED, shareUrl } from "@/lib/screen/url";
import { useUiUrlState } from "@/lib/screen/useUiUrlState";
import { onCommand, type GlintCommand } from "@/lib/commands";
import { encodeScreen } from "@/lib/screen/codec";
import { useRouter, useSearchParams } from "next/navigation";
import { useScreenUrlState } from "@/lib/screen/useScreenUrlState";
import { useDebounced } from "@/lib/useDebounced";
import { Tooltip } from "@/components/ui/Tooltip";
import { ColumnPicker } from "./ColumnPicker";
import { CompanyDrawer } from "./CompanyDrawer";
import { CompareSheet, CompareTray, resolvePinned } from "./Compare";
import { FiltersBar, FiltersSheet } from "./MobileFilters";
import { PHONE, useMediaQuery, WIDE } from "@/lib/useMediaQuery";
import { FilterPanel, type PickTarget } from "./FilterPanel";
import { MetricPicker } from "./MetricPicker";
import { NearMisses } from "./NearMisses";
import { RemovedPanel } from "./RemovedPanel";
import { type Include } from "./NearMisses";
import { Button } from "@/components/ui/Button";
import { relaxCondition } from "@/lib/screen/relax";
import { describeThreshold } from "@/lib/screen/nearMiss";
import { ResultsTable } from "./ResultsTable";
import { StatusBanner } from "./StatusBanner";
import { Toolbar } from "./Toolbar";

type Universe = components["schemas"]["Universe"];

/** Typing in an input, select or editable area: global shortcuts stay out of the way. */
function typingIn(el: EventTarget | null): boolean {
  return el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));
}

/** The main screen (SPEC §3.2): top bar, filter panel, sieve, results, near misses, drawer. */
export function Screener() {
  // The screen lives in ?s=: shared links open it, each settled edit is a history entry.
  const [screen, setScreen, { brokenLink }] = useScreenUrlState();
  // The selected ticker and open drawer live in ?t= and ?d=1 (replace, not push).
  const ui = useUiUrlState();
  const ticker = ui.drawer ? ui.ticker : null;
  const setTicker = (t: string | null) => ui.set(t ? { ticker: t, drawer: true } : { ticker: ui.ticker, drawer: false });
  const router = useRouter();
  const params = useSearchParams();
  const [highlight, setHighlight] = useState<number | null>(null);
  const [pick, setPick] = useState<PickTarget | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  // Below 1024px the rail is a summary bar and a sheet; below 768px the phone layout.
  const wide = useMediaQuery(WIDE, true);
  const phone = useMediaQuery(PHONE, false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [phoneMetricChoice, setPhoneMetricChoice] = useState<string | null>(null);
  const [universeOpen, setUniverseOpen] = useState(false);
  // Read by the page's key handler ("c" opens the comparison once two are pinned).
  const canCompare = useRef(false);
  const qc = useQueryClient();

  const meta = useMeta();
  const metricsQ = useMetrics();
  const presets = usePresets();
  const sectorsQ = useSectors();
  const metrics = useMemo(() => metricMap(metricsQ.data?.metrics ?? []), [metricsQ.data]);

  // Only complete filters run; edits settle for 250 ms before a request goes out. The results
  // say "Updating…" from the keystroke (§5.10: < 500 ms perceived; decisions/WT-09.md).
  const run = useMemo(() => runnable(screen, metrics), [screen, metrics]);
  const settled = useDebounced(run, 250);
  const result = useScreen(metricsQ.data ? withBadgeColumns(settled.screen, metrics) : null);

  const fresh = result.data;

  // New-entrant glint: rows not in the previous result set shimmer once (never on first load).
  const [glint, setGlint] = useState<{ seen: typeof fresh; seenScreen: Screen; tickers: Set<string>; fresh: Set<string> }>({
    seen: undefined,
    seenScreen: settled.screen,
    tickers: new Set(),
    fresh: new Set(),
  });
  if (fresh && !result.isPlaceholderData && fresh !== glint.seen) {
    const tickers = new Set(fresh.results.map((r) => r.ticker));
    const entered = glint.seen ? new Set([...tickers].filter((t) => !glint.tickers.has(t))) : new Set<string>();
    setGlint({ seen: fresh, seenScreen: settled.screen, tickers, fresh: entered });
  }
  // Live preview (docs/interaction-architecture.md): the screen evaluated in the browser on every
  // input, from the build's columns. The server's response replaces it once it's current for the
  // same screen; the two agree (engine.parity.test.ts), and a disagreement is logged.
  const snapshot = useSnapshot();
  const engine = useMemo(() => (snapshot.data && metricsQ.data ? new ScreenEngine(snapshot.data, metrics) : null), [snapshot.data, metricsQ.data, metrics]);
  const liveScreen = useMemo(() => withBadgeColumns(run.screen, metrics), [run.screen, metrics]);
  // Urgent: the funnel only (sieve and rail counts). Deferred: rows and near misses, built from
  // the deferred screen, so a drag never waits on them.
  const liveFunnel = useMemo(() => (engine ? engine.evaluate(liveScreen, { nearMisses: false, rank: false }).funnel : undefined), [engine, liveScreen]);
  const deferredLiveScreen = useDeferredValue(liveScreen);
  const liveFull = useMemo(
    // Every passing company (no 100-row cap): the table is virtualised.
    () => (engine && meta.data ? liveResponse(engine, deferredLiveScreen, engine.evaluate(deferredLiveScreen), meta.data.as_of, { limit: Infinity }) : undefined),
    [engine, deferredLiveScreen, meta.data],
  );
  const live = useMemo(
    () => (liveFull && liveFunnel ? { ...liveFull, funnel: liveFunnel, total: liveFunnel.at(-1)?.remaining ?? liveFull.total } : undefined),
    [liveFull, liveFunnel],
  );
  const serverCurrent = fresh !== undefined && !result.isPlaceholderData && settled === run;
  useEffect(() => {
    if (serverCurrent && live && fresh && deferredLiveScreen === liveScreen && !sameAnswer(live, fresh)) console.warn("Glint: the live preview and the server disagree; showing the server's result.", settled.screen);
  }, [serverCurrent, live, fresh, settled.screen, deferredLiveScreen, liveScreen]);

  // API down: React Query drops placeholder rows once the request fails, but §3.3 keeps the last
  // results on screen, greyed out. glint.seen is the last successful response.
  const data = serverCurrent ? fresh : (live ?? fresh ?? (result.isError ? glint.seen : undefined));
  // Label rows with the screen that produced them.
  const dataScreen = serverCurrent || live ? run.screen : glint.seenScreen;
  // Stale only when neither a current server answer nor a live preview is on screen.
  const stale = !serverCurrent && !live && (result.isPlaceholderData || (result.isError && data !== undefined) || settled !== run);
  const stepOf = live ? run.stepOf : settled.stepOf;
  const steps = stepOf.map((s) => (s !== null && !stale && !(result.isError && !live) ? (data?.funnel[s] ?? null) : null));
  // Dim only when what is shown may be out of date: no live preview and the server is behind.
  // An error means the server hasn't confirmed what's shown, so a live preview dims too.
  const busy = stale || (!live && result.isFetching) || (result.isError && data !== undefined);
  const dist = (metric: string) => (engine ? engine.distribution(run.screen.universe, metric) : null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || typingIn(e.target) || document.querySelector('[role="dialog"][aria-modal="true"]:not([inert])')) return;
      if (e.key === "f") {
        e.preventDefault();
        setPick({ mode: "add" });
      } else if (e.key === "c" && canCompare.current) {
        e.preventDefault();
        setCompareOpen(true);
      } else if ((e.key === "j" || e.key === "k") && !(e.target instanceof Element && e.target.closest("tbody tr"))) {
        // From anywhere on the page, j/k jump into the results at the current row; once a row
        // has focus, the table's own handler moves between rows.
        const row = document.querySelector<HTMLElement>('[data-testid="results-scroll"] tbody tr[tabindex="0"]');
        if (row) {
          e.preventDefault();
          row.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const loadPreset = async (id: string) => {
    const res = await qc.fetchQuery({
      queryKey: queryKeys.preset(id),
      queryFn: () => unwrap(api.GET("/api/presets/{preset_id}", { params: { path: { preset_id: id } } })),
      staleTime: Infinity,
    });
    setScreen(res.preset.screen);
    setTicker(null);
  };

  const patchUniverse = useStableCallback((patch: Partial<Universe>) =>
    setScreen((s) => ({ ...s, universe: { ...effectiveUniverse(s.universe), ...patch } })),
  );

  const onPick = useStableCallback((t: PickTarget) => setPick(t));
  const onPicked = (metric: string) => {
    const target = pick;
    setPick(null);
    if (!target) return;
    const c = newCondition(metric, metrics);
    // A new filter's metric becomes a column, so the table shows what the screen tests.
    const shown = (s: Screen) => (target.mode === "replace" ? s : withMetricColumn(s, metric, metrics.has(metric)));
    setScreen((prev) => {
      const s = shown(prev);
      switch (target.mode) {
        case "add":
          return addFilter(s, c);
        case "new_or":
          return addOrGroup(s, c);
        case "add_to_group":
          return addFilter(s, c, target.top);
        case "replace": {
          // Keep the missing policy when swapping metrics; the value's meaning changes, so it resets.
          const old = getAt(s, target.path);
          return updateAt(s, target.path, old && !isGroup(old) ? { ...c, missing: old.missing } : c);
        }
      }
    });
  };

  const onUpdate = useStableCallback((path: NodePath, c: Condition) => setScreen((s) => updateAt(s, path, c)));
  const onRemove = useStableCallback((path: NodePath) => setScreen((s) => removeAt(s, path)));

  /** Sieve click: the universe tray goes to the universe chips; a filter tray to its card. */
  const jumpToStep = (stepIndex: number) => {
    // Without the rail, a filter row only exists in the sheet: open it, then go to the row.
    if (!wide && stepIndex > 0 && !filtersOpen) {
      setFiltersOpen(true);
      setTimeout(() => focusStep(stepIndex), 60);
      return;
    }
    focusStep(stepIndex);
  };
  const focusStep = (stepIndex: number) => {
    const smooth = matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    if (stepIndex === 0) {
      // The universe rules live in the Universe panel: open it, then focus its list.
      setUniverseOpen(true);
      setTimeout(() => {
        const chips = document.getElementById("universe-chips");
        chips?.scrollIntoView({ behavior: smooth, block: "center" });
        chips?.focus({ preventScroll: true });
      }, 30);
      return;
    }
    const i = stepOf.indexOf(stepIndex);
    if (i < 0) return;
    setHighlight(i);
    const card = document.getElementById(`filter-${i}`);
    card?.scrollIntoView({ behavior: smooth, block: "center" });
    card?.focus({ preventScroll: true });
    setTimeout(() => setHighlight((h) => (h === i ? null : h)), 1500);
  };
  const labelFor = (s: { filter_path: (string | number)[] | null; label: string }) => stepLabel(s, dataScreen, metrics);

  const doExport = async () => {
    // Export what the table shows: the visible columns, badges included (SPEC §2.12).
    // Up to the API's 1,000-row maximum; say so when the result is larger.
    const total = data?.total ?? 0;
    const { blob, filename } = await exportScreen({ ...withBadgeColumns(run.screen, metrics), limit: Math.max(1, Math.min(1000, total)) });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    // Revoke later: some browsers (Safari, Firefox) cancel a download whose URL is revoked at once.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    return total > 1000 ? `CSV downloaded: the first 1,000 of ${formatCount(total)} rows.` : `CSV downloaded: ${formatCount(total)} rows.`;
  };

  // The table and near misses render from deferred copies: a threshold drag updates the sieve and
  // the rail's counts first, and the long lists catch up without blocking it. Their callbacks are
  // stable, so they skip re-rendering when nothing they show changed.
  const deferredData = useDeferredValue(data);
  const deferredScreen = useDeferredValue(dataScreen);
  const tableBadges = useMemo(() => (deferredData ? responseBadges(deferredData) : []), [deferredData]);
  const tableColumns = useMemo(() => (deferredData ? responseColumns(deferredData, deferredScreen) : []), [deferredData, deferredScreen]);
  const openTicker = useStableCallback((t: string) => setTicker(t));
  const openPage = useStableCallback((t: string) => router.push(companyHref(t, settled.screen)));
  const sortBy = useStableCallback((col: string, numeric: boolean) => setScreen((s) => ({ ...s, sort: nextSort(s, col, numeric) })));
  const toggleNearMisses = useStableCallback((on: boolean) => setScreen((s) => ({ ...s, near_misses: on })));
  const nearMissLabel = useStableCallback((m: components["schemas"]["NearMiss"]) => labelFor({ filter_path: m.failed_filter_path, label: m.failed_label }));
  const setUserColumns = useStableCallback((cols: string[]) => setScreen((s) => setColumns(s, cols)));
  const userCols = userColumns(screen).slice(1);
  const colsKey = userCols.join(",");
  const ranked = Boolean(screen.rank);
  const columnPicker = useMemo(
    () => <ColumnPicker columns={colsKey ? colsKey.split(",") : []} metrics={metrics} ranked={ranked} onChange={setUserColumns} />,
    [colsKey, metrics, ranked, setUserColumns],
  );

  const presetList = useMemo(() => presets.data?.presets ?? [], [presets.data]);
  const applyPreset = useStableCallback((id: string) => void loadPreset(id));
  const exportCsv = useStableCallback(() => doExport());
  const shareLink = useStableCallback(() => navigator.clipboard.writeText(shareUrl(window.location.origin, screen, { ticker: ui.ticker, drawer: ui.drawer, pinned: ui.pinned })));
  const sectorList = useMemo(() => (sectorsQ.data?.sectors ?? []).map((s) => s.sector), [sectorsQ.data]);

  // A selected sieve stage opens the list of companies it removed; the universe stage goes to
  // the universe rules.
  const [openStage, setOpenStage] = useState<number | null>(null);
  const selectStage = useStableCallback((step: components["schemas"]["FunnelStep"]) => {
    if (step.index === 0) return jumpToStep(0);
    setOpenStage((o) => (o === step.index ? null : step.index));
  });
  if (openStage !== null && data && !data.funnel[openStage]) setOpenStage(null);
  /** An edit from the removed list: map the runnable screen's filter back to the user's. */
  const changeStage = useStableCallback((path: NodePath, c: Condition) => {
    const userIndex = run.stepOf.indexOf(path.top + 1);
    if (userIndex >= 0) setScreen((s) => updateAt(s, { top: userIndex }, c));
  });
  const missingName = useStableCallback((step: components["schemas"]["FunnelStep"]) => {
    const node = run.screen.filters?.children?.[step.index - 1];
    return node && !isGroup(node) ? (metrics.get(node.metric)?.name ?? node.metric) : null;
  });

  // Crisp columns: the metrics this screen filters or ranks on.
  const screened = useMemo(() => {
    const ids = new Set<string>();
    const walk = (n: Condition | Group) => (isGroup(n) ? (n.children ?? []).forEach(walk) : ids.add(n.metric));
    (run.screen.filters?.children ?? []).forEach(walk);
    for (const f of run.screen.rank?.factors ?? []) ids.add(f.metric);
    return ids;
  }, [run.screen]);
  // Pins for comparison live in ?c= (at most three; pinning a fourth drops the oldest).
  const pinnedKey = (ui.pinned ?? []).join(",");
  const pinnedList = useMemo(() => (pinnedKey ? pinnedKey.split(",") : []), [pinnedKey]);
  const togglePin = useStableCallback((t: string) => {
    ui.update((cur) => {
      const pins = cur.pinned ?? [];
      const T = t.toUpperCase();
      return { ...cur, pinned: pins.includes(T) ? pins.filter((x) => x !== T) : [...pins, T].slice(-MAX_PINNED) };
    });
  });
  const clearPins = useStableCallback(() => {
    ui.update((cur) => ({ ...cur, pinned: [] }));
    setCompareOpen(false);
  });
  const pinnedResolved = useMemo(() => resolvePinned(engine, pinnedList), [engine, pinnedList]);
  useEffect(() => {
    canCompare.current = pinnedList.length >= 2;
  });
  const openCompare = useStableCallback(() => setCompareOpen(true));
  const closeCompare = useStableCallback(() => setCompareOpen(false));
  const openFromCompare = useStableCallback((t: string) => {
    setCompareOpen(false);
    setTicker(t);
  });
  const percentileOf = useStableCallback((metric: string, cik: string) => {
    const row = engine?.store.index.get(cik);
    return engine && row !== undefined ? engine.sectorPercentile(run.screen.universe, metric, row) : null;
  });

  // The drawer flicks through results in table order (j/k, "12 of 139").
  const tableRowsForOrder = liveFull?.results ?? deferredData?.results;
  const resultOrder = useMemo(() => (tableRowsForOrder ?? []).map((r) => r.ticker), [tableRowsForOrder]);
  const closeDrawer = useStableCallback(() => setTicker(null));

  // "Include" for a near miss: relax the filter it missed just far enough, and preview the result
  // count with the live engine (cached per screen).
  const includeCache = useRef<{ screen: Screen | null; engine: ScreenEngine | null; map: Map<string, Include | null> }>({ screen: null, engine: null, map: new Map() });
  const includeFor = useStableCallback((m: components["schemas"]["NearMiss"]): Include | null => {
    const cache = includeCache.current;
    if (cache.screen !== run.screen || cache.engine !== engine) {
      cache.screen = run.screen;
      cache.engine = engine;
      cache.map = new Map();
    }
    const key = `${m.cik}|${m.failed_filter_path.join(".")}`;
    if (cache.map.has(key)) return cache.map.get(key) ?? null;
    const k = m.failed_filter_path[2];
    const node = typeof k === "number" ? run.screen.filters?.children?.[k] : undefined;
    let out: Include | null = null;
    if (engine && node && !isGroup(node)) {
      const pct = m.cmp === "pct_rank_gte" || m.cmp === "pct_rank_lte";
      const relaxed = relaxCondition(node, m.value, pct && typeof m.value === "number" ? m.value : null, unitOf(node.metric, metrics));
      if (relaxed && typeof k === "number") {
        const final = run.screen.filters?.children?.length ?? 0;
        const count = engine.evaluate(updateAt(run.screen, { top: k }, relaxed), { nearMisses: false, rank: false }).funnel[final]?.remaining;
        const current = engine.evaluate(run.screen, { nearMisses: false, rank: false }).funnel[final]?.remaining;
        if (count !== undefined && current !== undefined) out = { count, current, apply: () => changeStage({ top: k }, relaxed) };
      }
    }
    cache.map.set(key, out);
    return out;
  });

  // Palette commands (CommandPalette sends them while the screener is mounted).
  const commandRef = useRef<(c: GlintCommand) => void>(() => {});
  useEffect(() => {
    commandRef.current = (c: GlintCommand) => {
      if (c.kind === "open-company") setTicker(c.ticker);
      else if (c.kind === "apply-preset") void loadPreset(c.id);
      else if (c.kind === "add-filter") setScreen((s) => addFilter(withMetricColumn(s, c.metric, metrics.has(c.metric)), newCondition(c.metric, metrics)));
      else if (c.kind === "share") void navigator.clipboard.writeText(shareUrl(window.location.origin, screen, { ticker: ui.ticker, drawer: ui.drawer, pinned: ui.pinned }));
      else if (c.kind === "export") void doExport();
      else if (c.kind === "pin-company") togglePin(c.ticker);
      else if (c.kind === "compare" && pinnedList.length >= 2) setCompareOpen(true);
    };
  });
  useEffect(() => onCommand((c) => commandRef.current(c)), []);

  // ?preset=<id> (the palette, off the screener): load it once, then drop the param.
  const presetParam = params.get("preset");
  useEffect(() => {
    if (!presetParam) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("preset");
    window.history.replaceState(null, "", url.pathname + url.search);
    void loadPreset(presetParam);
    // loadPreset is stable enough for a one-shot on the param; re-running on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetParam]);

  const filterPanel = (
    <FilterPanel
      screen={screen}
      metrics={metrics}
      sectors={sectorList}
      steps={steps}
      dist={dist}
      highlight={highlight}
      onUpdate={onUpdate}
      onRemove={onRemove}
      onPick={onPick}
    />
  );
  // Phones show ticker, name, score and one metric the viewer picks from the table's columns
  // (only those the response carries), defaulting to the first one the screen uses.
  const FIXED = new Set(["ticker", "name", "rank_score"]);
  const metricChoices = tableColumns.filter((c) => !FIXED.has(c));
  const phoneMetric = (phoneMetricChoice && metricChoices.includes(phoneMetricChoice) ? phoneMetricChoice : null) ?? metricChoices.find((c) => screened.has(c)) ?? metricChoices[0] ?? null;
  const phoneColumns = tableColumns.filter((c) => FIXED.has(c) || c === phoneMetric);
  const phoneMetricPicker = (
    <label className="flex items-center gap-1.5 text-label text-ink-soft">
      <span className="text-muted">Showing</span>
      <select
        value={phoneMetric ?? ""}
        onChange={(e) => setPhoneMetricChoice(e.target.value)}
        aria-label="Metric column"
        className="h-ctl max-w-[10rem] rounded-control border border-line-strong bg-paper px-2 text-label"
      >
        {metricChoices.map((c) => (
          <option key={c} value={c}>
            {metrics.get(c)?.name ?? (c === "sector" ? "Sector" : c)}
          </option>
        ))}
      </select>
    </label>
  );
  // A failed load with nothing to show: the banner says why, so no skeletons pretend to load.
  const loadError = result.error ?? metricsQ.error ?? meta.error;
  const nothingComing = Boolean(loadError) && !data;
  const finalStep = data?.funnel.at(-1);
  const bindingStep = data?.funnel.find((st) => st.binding);
  const sieveLine = data
    ? `${formatCount(data.funnel[0]?.remaining ?? 0)} in the universe${bindingStep ? `; ${labelFor(bindingStep)} removes the most` : ""}.`
    : null;

  return (
    <div className={`flex min-h-[calc(100dvh-7rem)] flex-col ${pinnedList.length > 0 ? "pb-24 sm:pb-16" : ""}`}>
      <Toolbar
        name={screen.name}
        universe={screen.universe}
        onUniverse={patchUniverse}
        presets={presetList}
        onPreset={applyPreset}
        buildCount={meta.data?.universe_counts?.companies ?? null}
        excluded={data?.funnel[0]?.removed ?? null}
        onExport={exportCsv}
        onShare={shareLink}
        compact={phone}
        universeOpen={universeOpen}
        onUniverseOpen={setUniverseOpen}
      />

      <div className="grid flex-1 gap-4 p-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
        {wide && (
          <aside aria-label="Screen definition" className="lg:sticky lg:top-24 lg:max-h-[calc(100dvh-8rem)] lg:self-start lg:overflow-y-auto lg:pr-1">
            {filterPanel}
          </aside>
        )}

        <main className="min-w-0 space-y-4" aria-busy={busy}>
          {!wide && (
            <FiltersBar
              filters={screen.filters?.children?.length ?? 0}
              results={finalStep?.remaining ?? null}
              onOpen={() => setFiltersOpen(true)}
              summary={phone ? sieveLine : null}
            />
          )}
          <StatusBanner error={loadError} keptStale={data !== undefined} preview={Boolean(live) && !serverCurrent} />
          {brokenLink && (
            <div role="alert" className="rounded-panel border border-caution/60 bg-caution/10 p-panel text-label">
              <p className="font-medium">This link&apos;s screen couldn&apos;t be read.</p>
              <p className="text-muted">The screener opened with an empty screen. The link is unchanged in the address bar; it may be cut off or from another app.</p>
            </div>
          )}

          {!phone && !nothingComing && (
          <section aria-labelledby="sieve-h" className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 id="sieve-h" className="text-section font-semibold text-ink-soft">
                Sieve
              </h2>
              <Tooltip
                tip={
                  <>
                    Each tray is what&apos;s left after that filter, in your order. The hatched part of a bar is companies removed because they have no
                    value for it. &ldquo;Removes the most&rdquo; marks the filter that removes the most. Select a tray to list the companies it
                    removed.
                  </>
                }
              >
                <span className="text-meta text-muted" role="img" aria-label="How to read the sieve">
                  <Icon name="info" />
                </span>
              </Tooltip>
            </div>
            {data ? (
              <SieveBar steps={data.funnel} dimmed={busy} onSelect={selectStage} selected={openStage} labelFor={labelFor} missingName={missingName} />
            ) : (
              <div className="h-16 animate-pulse rounded-panel bg-dune" aria-hidden />
            )}
          </section>
          )}

          {openStage !== null && data && data.funnel[openStage] && (
            <RemovedPanel
              engine={engine}
              screen={run.screen}
              step={data.funnel[openStage]}
              label={labelFor(data.funnel[openStage])}
              metrics={metrics}
              onChange={changeStage}
              onEdit={() => jumpToStep(openStage)}
              onClose={() => setOpenStage(null)}
            />
          )}

          {data && data.warnings.length > 0 && (
            <ul className="space-y-1 text-meta text-caution">
              {data.warnings.map((w) => (
                <li key={w} className="flex items-baseline gap-1.5">
                  <Icon name="warning" />
                  {w}
                </li>
              ))}
            </ul>
          )}

          {data ? (
            <div>
              {data.total === 0 ? (
                <div className={stale ? "opacity-50 transition-opacity duration-200" : "transition-opacity duration-200"}>
                  <EmptyResult funnel={data.funnel} labelFor={labelFor} nearMisses={data.near_misses} includeFor={includeFor} metrics={metrics} screen={run.screen} />
                </div>
              ) : (
                <ResultsTable
                  pending={busy}
                  rows={liveFull?.results ?? deferredData?.results ?? data.results}
                  badges={tableBadges}
                  total={deferredData?.total ?? data.total}
                  screen={deferredScreen}
                  columns={phone ? phoneColumns : tableColumns}
                  compact={phone}
                  metrics={metrics}
                  selected={ticker}
                  freshTickers={glint.fresh}
                  onOpen={openTicker}
                  onOpenPage={openPage}
                  onSort={sortBy}
                  screened={screened}
                  pinned={pinnedList}
                  onPin={togglePin}
                  percentile={percentileOf}
                  actions={phone ? phoneMetricPicker : columnPicker}
                />
              )}
            </div>
          ) : result.isPending && !result.isError && !nothingComing ? (
            <div className="space-y-1" role="status" aria-label="Loading results">
              {Array.from({ length: 8 }, (_, k) => (
                <div key={k} className="h-row animate-pulse rounded-panel bg-dune" />
              ))}
            </div>
          ) : null}

          {data && (
            <NearMisses
              items={deferredData?.near_misses ?? data.near_misses}
              enabled={screen.near_misses}
              onToggle={toggleNearMisses}
              metrics={metrics}
              onOpen={openTicker}
              labelFor={nearMissLabel}
              includeFor={includeFor}
              defaultOpen={!phone}
            />
          )}
        </main>
      </div>

      <CompanyDrawer
        ticker={ticker}
        screen={settled.screen}
        onClose={closeDrawer}
        order={resultOrder}
        onNavigate={openTicker}
        pinned={pinnedList}
        onPin={togglePin}
      />
      {!wide && (
        <FiltersSheet open={filtersOpen} onClose={() => setFiltersOpen(false)} side={phone ? "bottom" : "left"} results={finalStep?.remaining ?? null}>
          {phone && data && (
            <section aria-label="Sieve" className="space-y-1">
              <SieveBar steps={data.funnel} dimmed={busy} onSelect={(st) => jumpToStep(st.index)} selected={null} labelFor={labelFor} missingName={missingName} />
            </section>
          )}
          {filterPanel}
        </FiltersSheet>
      )}
      <CompareTray pinned={pinnedResolved} onRemove={togglePin} onClear={clearPins} onOpen={openCompare} />
      <CompareSheet
        open={compareOpen && pinnedList.length > 0}
        onClose={closeCompare}
        engine={engine}
        screen={settled.screen}
        pinned={pinnedResolved}
        defs={metrics}
        onOpenCompany={openFromCompare}
        onUnpin={togglePin}
      />
      <MetricPicker
        open={pick !== null}
        title={pick?.mode === "replace" ? "Change metric" : pick?.mode === "new_or" ? "Start an OR group" : "Add a filter"}
        metrics={metricsQ.data?.metrics ?? []}
        onPick={onPicked}
        onClose={() => setPick(null)}
      />
    </div>
  );
}

/**
 * Zero results: the advice comes from the near misses ("Lowering FCF margin to 7.4% adds 1
 * company", with a button that does it), not from the filter that removed the most, because
 * loosening a threshold can't bring back companies that have no value.
 */
function EmptyResult({
  funnel,
  labelFor,
  nearMisses,
  includeFor,
  metrics,
  screen,
}: {
  funnel: components["schemas"]["FunnelStep"][];
  labelFor: (s: components["schemas"]["FunnelStep"]) => string;
  nearMisses: components["schemas"]["NearMiss"][];
  includeFor: (m: components["schemas"]["NearMiss"]) => Include | null;
  metrics: Map<string, MetricDefinition>;
  screen: Screen;
}) {
  const filters = funnel.length - 1;
  const best = nearMisses
    .slice(0, 12)
    .map((m) => ({ m, inc: includeFor(m) }))
    .find(({ inc }) => inc !== null && inc.count > inc.current);
  const binding = funnel.find((s) => s.binding);
  if (filters === 0) {
    return (
      <div className="space-y-2 rounded-panel bg-paper p-panel">
        <p className="text-prose text-ink-soft">The universe itself is empty. Widen it with the universe rules above.</p>
      </div>
    );
  }
  if (best && best.inc) {
    const node = screen.filters?.children?.[best.m.failed_filter_path[2] as number];
    const name = node && !isGroup(node) ? (metrics.get(node.metric)?.name ?? node.metric) : best.m.metric;
    const verb = best.m.cmp.endsWith("lte") || best.m.cmp === "lt" ? "Raising" : best.m.cmp === "between" ? "Widening" : "Lowering";
    const added = best.inc.count - best.inc.current;
    const target = best.m.value === null ? "" : ` to ${describeThreshold({ ...best.m, threshold: best.m.value }, metrics).replace(/^(≥|≤|>|<|between|percentile ≥|percentile ≤)\s*/, "")}`;
    return (
      <div className="space-y-2 rounded-panel bg-paper p-panel">
        <p className="text-prose text-ink-soft">
          {noneLine(filters)} {verb} {name}
          {target} adds {formatCount(added)} {added === 1 ? "company" : "companies"}.
        </p>
        <Button variant="primary" onClick={best.inc.apply}>
          {{ Lowering: "Lower", Raising: "Raise", Widening: "Widen" }[verb]} {name}
          {target}
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-2 rounded-panel bg-paper p-panel">
      <p className="text-prose text-ink-soft">
        {noneLine(filters)}
        {binding && filters > 1
          ? ` ${labelFor(binding)} removes the most${binding.removed_missing > binding.removed / 2 ? `, mostly companies with no value for it, so try letting missing values pass` : ""}.`
          : binding && binding.removed_missing > binding.removed / 2
            ? " Most of the companies it removes have no value for it, so try letting missing values pass."
            : ""}
      </p>
    </div>
  );
}

/** The full company page, carrying the screen so the page can show its screen check. */
function companyHref(ticker: string, screen: Screen): string {
  return `/company/${encodeURIComponent(ticker)}${screen.filters?.children?.length ? `?s=${encodeScreen(screen)}` : ""}`;
}

/** "No company passes the filter." or "No company passes all 3 filters." */
function noneLine(filters: number): string {
  return filters === 1 ? "No company passes the filter." : `No company passes all ${formatCount(filters)} filters.`;
}
