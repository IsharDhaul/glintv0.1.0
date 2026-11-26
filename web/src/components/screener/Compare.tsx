"use client";

import { useEffect, useId, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { KEY_METRICS } from "@/components/company/CompanyView";
import { Button, IconButton } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { FadeScroller } from "@/components/ui/FadeScroller";
import { Icon } from "@/components/ui/Icon";
import { MetricValue } from "@/components/ui/MetricValue";
import { NullValue } from "@/components/ui/NullValue";
import { PercentileTick } from "@/components/ui/PercentileTick";
import { noteAt } from "@/lib/data/snapshot";
import { describePercentile, formatCount, formatPrice } from "@/lib/format";
import { displayName } from "@/lib/names";
import { NOTE_DISPLAY, type CellNote } from "@/lib/notes";
import { useScrollEdges } from "@/lib/useScrollEdges";
import { describeCondition } from "@/lib/screen/describe";
import type { ScreenEngine } from "@/lib/screen/engine";
import { MAX_PINNED } from "@/lib/screen/url";
import { isGroup, type Condition, type Group, type MetricDefinition, type Screen } from "@/lib/screen/types";

/** A pinned ticker found in the build: its row in the snapshot plus the facts the header shows. */
export type Pinned = { ticker: string; row: number | null; name: string | null; sector: string | null; exchange: string | null; foreign: boolean };

/** Look pinned tickers up in the build's snapshot (null row: not in this build). */
export function resolvePinned(engine: ScreenEngine | null, tickers: readonly string[]): Pinned[] {
  const rows = engine?.store.rows;
  return tickers.map((ticker) => {
    const i = rows ? rows.ticker.findIndex((t) => t.toUpperCase() === ticker.toUpperCase()) : -1;
    if (!rows || i < 0) return { ticker, row: null, name: null, sector: null, exchange: null, foreign: false };
    return { ticker, row: i, name: rows.name[i] ?? null, sector: rows.sector[i] ?? null, exchange: rows.exchange[i] ?? null, foreign: rows.is_foreign_filer[i] ?? false };
  });
}

/**
 * The compare tray (docs/glint-ui-upgrade.md Phase 4.9): pinned tickers as removable chips along
 * the bottom of the screener, with Compare and Clear. Hidden when nothing is pinned.
 */
export function CompareTray({
  pinned,
  onRemove,
  onClear,
  onOpen,
}: {
  pinned: Pinned[];
  onRemove: (ticker: string) => void;
  onClear: () => void;
  onOpen: () => void;
}) {
  if (pinned.length === 0) return null;
  return (
    <section aria-label="Compare tray" className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-paper/95 shadow-overlay backdrop-blur-sm">
      <div className="mx-auto flex max-w-screen-2xl items-center gap-2 px-4 py-2">
        <span className="hidden text-label font-semibold text-ink-soft sm:inline">Compare</span>
        <FadeScroller className="min-w-0 flex-1 sm:flex-initial" aria-label="Pinned companies">
          <ul className="flex flex-nowrap items-center gap-1.5 py-0.5">
          {pinned.map((p) => (
            <li key={p.ticker}>
              <Chip onRemove={() => onRemove(p.ticker)} removeLabel={`Unpin ${p.ticker}`}>
                <span className="num font-medium text-ink">{p.ticker}</span>
                {p.name && <span className="hidden truncate text-muted sm:inline">{displayName(p.name)}</span>}
              </Chip>
            </li>
          ))}
          </ul>
        </FadeScroller>
        <span className="hidden text-meta text-muted lg:inline">
          {pinned.length < MAX_PINNED ? `Pin up to ${formatCount(MAX_PINNED - pinned.length)} more with x.` : `${formatCount(MAX_PINNED)} is the most; pinning another drops the oldest.`}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <Button variant="ghost" onClick={onClear}>
            Clear
          </Button>
          <Button variant="primary" onClick={onOpen} disabled={pinned.length < 2} aria-keyshortcuts="c">
            {pinned.length < 2 ? (
              <>
                <span className="sm:hidden">Compare</span>
                <span className="hidden sm:inline">Pin another to compare</span>
              </>
            ) : (
              `Compare ${formatCount(pinned.length)}`
            )}
          </Button>
        </span>
      </div>
    </section>
  );
}

type Row = { key: string; metric: string; label: string; path: string | null; screened: boolean };

/** The screen's leaf conditions and ranked factors, in order; with no screen, a fixed key set. */
function rowsFor(screen: Screen, defs: Map<string, MetricDefinition>): Row[] {
  const out: Row[] = [];
  const walk = (n: Condition | Group, path: (string | number)[]) => {
    if (isGroup(n)) return (n.children ?? []).forEach((c, k) => walk(c, [...path, "children", k]));
    out.push({ key: path.join("."), metric: n.metric, label: describeCondition(n, defs), path: path.join("."), screened: true });
  };
  (screen.filters?.children ?? []).forEach((c, k) => walk(c, ["filters", "children", k]));
  for (const f of screen.rank?.factors ?? []) {
    if (out.some((r) => r.metric === f.metric)) continue;
    out.push({ key: `rank.${f.metric}`, metric: f.metric, label: `${defs.get(f.metric)?.name ?? f.metric}, ranked`, path: null, screened: true });
  }
  if (out.length > 0) return out;
  return KEY_METRICS.filter((m) => defs.has(m)).map((m) => ({ key: m, metric: m, label: defs.get(m)?.name ?? m, path: null, screened: false }));
}

/**
 * Side by side (Phase 4.9): the pinned companies' screen metrics with each one's sector
 * percentile and pass or fail, from the build's columns. Percentiles are within each company's own
 * sector, so when the sectors differ (or a filer reports under another regime) the sheet says the
 * columns aren't a ranking of these companies against each other.
 */
export function CompareSheet({
  open,
  onClose,
  engine,
  screen,
  pinned,
  defs,
  onOpenCompany,
  onUnpin,
}: {
  open: boolean;
  onClose: () => void;
  engine: ScreenEngine | null;
  screen: Screen;
  pinned: Pinned[];
  defs: Map<string, MetricDefinition>;
  onOpenCompany: (ticker: string) => void;
  onUnpin: (ticker: string) => void;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
      } else if (e.key === "Tab" && panel.current) {
        const f = panel.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])');
        const first = f[0];
        const last = f[f.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [open]);

  const rows = useMemo(() => rowsFor(screen, defs), [screen, defs]);
  const outcomes = useMemo(() => {
    if (!open || !engine) return new Map<number, Map<string, boolean>>();
    const ev = engine.evaluate(screen, { nearMisses: false, rank: false });
    const out = new Map<number, Map<string, boolean>>();
    for (const p of pinned) {
      if (p.row === null) continue;
      out.set(p.row, new Map(ev.whyPassed(p.row).map((o) => [o.filter_path.join("."), o.passed])));
    }
    return out;
  }, [open, engine, screen, pinned]);

  if (!open) return null;
  const filters = rows.filter((r) => r.path !== null).length;
  const found = pinned.filter((p) => p.row !== null);
  const sectors = [...new Set(found.map((p) => p.sector).filter(Boolean))] as string[];
  const foreign = found.filter((p) => p.foreign).map((p) => p.ticker);

  const cellNote = (metric: string, row: number): CellNote | null => {
    const code = engine ? noteAt(engine.store, metric, row) : null;
    return code ? { code, message: NOTE_DISPLAY[code].label } : null;
  };

  return createPortal(
    <div className="fixed inset-x-0 top-banner bottom-0 z-40 flex items-end justify-center bg-ink/30" onMouseDown={onClose}>
      <div
        ref={panel}
        role="dialog"
        data-compare
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(e) => e.stopPropagation()}
        className="in-sheet flex max-h-[85dvh] w-full max-w-5xl flex-col rounded-t-sheet bg-paper shadow-overlay"
      >
        <header className="flex items-start justify-between gap-3 border-b border-line p-panel">
          <div>
            <h2 id={titleId} className="text-section font-semibold text-ink">
              Compare {formatCount(pinned.length)} companies
            </h2>
            <p className="text-label text-ink-soft">{rows[0]?.screened ? `${screen.name}: each filter, with the company's percentile in its own sector.` : "Key metrics, with each company's percentile in its own sector."}</p>
          </div>
          <button ref={closeBtn} type="button" onClick={onClose} className="inline-flex h-ctl items-center gap-1 rounded-control px-2 text-label text-muted hover:text-ink-soft">
            Close <span className="text-meta">(Esc)</span>
          </button>
        </header>

        {(sectors.length > 1 || foreign.length > 0) && (
          <p role="note" className="mx-panel mt-panel flex items-baseline gap-1.5 rounded-panel border-l-2 border-caution bg-caution/10 px-3 py-2 text-label text-ink-soft">
            <Icon name="warning" className="text-caution" />
            <span>
              {sectors.length > 1 && <>These companies are in different sectors ({sectors.join(", ")}). Each percentile is within its own sector, so the columns aren&apos;t a ranking of these companies against each other. </>}
              {foreign.length > 0 && <>{foreign.join(", ")} {foreign.length === 1 ? "files" : "file"} as a foreign private issuer; currency and accounting standard may differ.</>}
            </span>
          </p>
        )}

        <SheetScroller>
          <table className="w-full border-collapse text-cell">
            <caption className="sr-only">Pinned companies side by side</caption>
            <thead>
              <tr className="border-b border-line align-bottom">
                <th scope="col" className="sticky left-0 bg-paper py-2 pr-4 text-left text-head font-medium text-muted">
                  <span className="sr-only">Metric</span>
                </th>
                {pinned.map((p) => (
                  <th key={p.ticker} scope="col" className="min-w-36 px-3 py-2 text-left font-normal sm:min-w-44">
                    <div className="flex items-start justify-between gap-1">
                      <button type="button" onClick={() => onOpenCompany(p.ticker)} className="num text-section font-semibold text-forest underline-offset-2 hover:underline">
                        {p.ticker}
                      </button>
                      <IconButton label={`Unpin ${p.ticker}`} onClick={() => onUnpin(p.ticker)}>
                        <Icon name="close" />
                      </IconButton>
                    </div>
                    <div className="truncate text-label text-ink-soft">{p.name ? displayName(p.name) : "Not in this build"}</div>
                    {p.sector && <div className="text-meta text-muted">{[p.sector, p.exchange].filter(Boolean).join(", ")}</div>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <FigureRow label="Price" pinned={pinned} render={(row) => {
                const v = engine?.cell("price", row);
                return typeof v === "number" ? <span className="num font-medium text-ink">{formatPrice(v)}</span> : <NullValue note={cellNote("price", row)} />;
              }} />
              <FigureRow label="Market cap" pinned={pinned} render={(row) => (
                <span className="num font-medium text-ink">
                  <MetricValue def={defs.get("market_cap") ?? { id: "market_cap", unit: "usd" }} value={engine?.cell("market_cap", row) as number | null} note={cellNote("market_cap", row)} />
                </span>
              )} />
              {filters > 0 && (
                <FigureRow label="Screen check" pinned={pinned} render={(row) => {
                  const o = outcomes.get(row);
                  if (!o || o.get("universe") === false) return <span className="text-label text-ink-soft">Outside the screen&apos;s universe</span>;
                  const failed = rows.filter((r) => r.path !== null && o.get(r.path) === false).length;
                  return failed === 0 ? (
                    <span className="inline-flex items-center gap-1 text-label text-ink-soft"><Icon name="check" className="text-forest" />Passes all {formatCount(filters)}</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-label text-ink-soft"><Icon name="cross" className="text-neg" />Fails {formatCount(failed)} of {formatCount(filters)}</span>
                  );
                }} />
              )}
              {rows.map((r) => {
                const def = defs.get(r.metric);
                return (
                  <tr key={r.key} className="border-b border-line align-top">
                    <th scope="row" className="sticky left-0 z-10 w-32 min-w-32 bg-paper py-2 pr-3 text-left text-label font-normal text-ink-soft sm:w-auto sm:min-w-44 sm:pr-4">
                      {r.label}
                    </th>
                    {pinned.map((p) => {
                      if (p.row === null) return <td key={p.ticker} className="px-3 py-2"><NullValue note={null} fallbackReason="Not in this build." /></td>;
                      const row = p.row;
                      const value = engine?.cell(r.metric, row) ?? null;
                      const passed = r.path ? outcomes.get(row)?.get(r.path) : undefined;
                      const pct = def && def.unit !== "bool" && engine ? engine.sectorPercentile(screen.universe, r.metric, row) : null;
                      return (
                        <td key={p.ticker} className="px-3 py-2">
                          <div className="flex items-center gap-1.5">
                            {passed !== undefined && (
                              <span className={passed ? "text-forest" : "text-neg"}>
                                <Icon name={passed ? "check" : "cross"} />
                                <span className="sr-only">{passed ? "Passed" : "Failed"}</span>
                              </span>
                            )}
                            <span className={`num ${r.screened ? "font-medium text-ink" : "text-ink-soft"}`}>
                              {typeof value === "string" ? value : <MetricValue def={def ?? { id: r.metric, unit: "score" }} value={value} note={cellNote(r.metric, row)} />}
                            </span>
                          </div>
                          {pct !== null && def && (
                            <div className="mt-0.5">
                              <PercentileTick p={pct} said={describePercentile(pct, def.better, p.sector ?? "its sector")} />
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-meta text-muted">Values come from this build&apos;s SEC filings and prices. Percentiles are within each company&apos;s sector, over the screen&apos;s universe.</p>
        </SheetScroller>
      </div>
    </div>,
    document.body,
  );
}

function FigureRow({ label, pinned, render }: { label: string; pinned: Pinned[]; render: (row: number) => React.ReactNode }) {
  return (
    <tr className="border-b border-line align-top">
      <th scope="row" className="sticky left-0 z-10 w-32 min-w-32 bg-paper py-2 pr-3 text-left text-label font-normal text-ink-soft sm:w-auto sm:min-w-44 sm:pr-4">
        {label}
      </th>
      {pinned.map((p) => (
        <td key={p.ticker} className="px-3 py-2">
          {p.row === null ? <NullValue note={null} fallbackReason="Not in this build." /> : render(p.row)}
        </td>
      ))}
    </tr>
  );
}

/** The sheet's table scroller: its trailing edge fades while companies are hidden to the right. */
function SheetScroller({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useScrollEdges(ref);
  return (
    <div ref={ref} className="fade-x-end flex-1 overflow-auto p-panel">
      {children}
    </div>
  );
}
