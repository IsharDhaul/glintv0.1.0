"use client";

import { useScrollEdges } from "@/lib/useScrollEdges";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { IconSwap } from "@/components/ui/IconSwap";
import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { memo } from "react";
import { Icon } from "@/components/ui/Icon";
import { MetricValue } from "@/components/ui/MetricValue";
import { displayName } from "@/lib/names";
import { NullValue } from "@/components/ui/NullValue";
import { Tooltip } from "@/components/ui/Tooltip";
import { formatCount, formatValue } from "@/lib/format";
import { effectiveSort } from "@/lib/screen/columns";
import type { MetricDefinition, ResultRow, Screen } from "@/lib/screen/types";
import { columnDef, type ColumnDef } from "./columns";

// Table settings (decisions file): core features only. Sorting is server-side because the API
// applies `limit` after sorting, so the table never re-orders rows itself.
const features = tableFeatures({});
const helper = createColumnHelper<typeof features, ResultRow>();
const noRows: ResultRow[] = [];
const EMPTY: ReadonlySet<string> = new Set();
const EMPTY_LIST: readonly string[] = [];

type Meta = { def: ColumnDef; kind: "index" | "ticker" | "value" | "flags" | "coverage" };

/**
 * Results (SPEC §3.2, WT-05 step 6): TanStack Table + Virtual, pinned ticker, server sorting,
 * "—" / "n/m" with reasons, flag and coverage badges. Click or Enter opens the drawer; j/k and
 * ↑/↓ move between rows.
 */
export const ResultsTable = memo(function ResultsTable({
  rows,
  total,
  screen,
  columns,
  metrics,
  selected,
  freshTickers,
  onOpen,
  onOpenPage,
  onSort,
  actions,
  badges,
  pending = false,
  screened = EMPTY,
  pinned = EMPTY_LIST,
  onPin,
  percentile,
  compact = false,
}: {
  rows: ResultRow[];
  total: number;
  screen: Screen;
  /** User columns, ticker first. */
  columns: string[];
  metrics: Map<string, MetricDefinition>;
  selected: string | null;
  /** Tickers that newly entered since the last run: one glint each. */
  freshTickers: ReadonlySet<string>;
  onOpen: (ticker: string) => void;
  /** "o" on a row: the full company page. */
  onOpenPage?: (ticker: string) => void;
  onSort: (column: string, numeric: boolean) => void;
  actions?: ReactNode;
  /** Badge columns the response carries (only live metrics are requested). */
  badges: string[];
  /** An edit hasn't settled or its request is in flight: the rows are the previous result. */
  pending?: boolean;
  /** Metric ids the screen filters or ranks on: those columns are crisp, the rest soft. */
  screened?: ReadonlySet<string>;
  /** Tickers pinned for comparison. */
  pinned?: readonly string[];
  /** "x" on a row: pin or unpin it. */
  onPin?: (ticker: string) => void;
  /** Sector percentile (0..1) of a company's value, for the hover tick; null when there is none. */
  percentile?: (metric: string, cik: string) => number | null;
  /** Phones: no rank or badge columns (the caller passes ticker, name, score and one metric). */
  compact?: boolean;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  // Touch screens keep a "hover" after a tap, which would leave one row's tick showing.
  const canHover = useMediaQuery("(hover: hover)", true);
  const sort = effectiveSort(screen);

  const tableColumns = useMemo(() => {
    const meta = (def: ColumnDef, kind: Meta["kind"]): Meta => ({ def, kind });
    return helper.columns([
      ...(compact ? [] : [helper.display({ id: "#", header: "#", meta: meta({ id: "#", label: "#", unit: "score", numeric: true, definition: null }, "index") })]),
      ...columns.map((id) =>
        helper.accessor((r) => r.values[id], { id, header: columnDef(id, metrics).label, meta: meta(columnDef(id, metrics), id === "ticker" ? "ticker" : "value") }),
      ),
      ...(!compact && badges.includes("flag_count") ? [helper.accessor((r) => r.values.flag_count, { id: "flag_count", header: "Flags", meta: meta(columnDef("flag_count", metrics), "flags") })] : []),
      ...(!compact && badges.includes("data_coverage") ? [helper.accessor((r) => r.values.data_coverage, { id: "data_coverage", header: "Cov.", meta: meta(columnDef("data_coverage", metrics), "coverage") })] : []),
    ]);
  }, [columns, metrics, badges, compact]);

  const table = useTable({ features, columns: tableColumns, data: rows.length ? rows : noRows, getRowId: (r) => r.cik });
  const tableRows = table.getRowModel().rows;

  const scrollRef = useRef<HTMLDivElement>(null);
  useScrollEdges(scrollRef); // fades the trailing edge while columns are hidden to the right
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual is designed for this; the compiler just skips memoizing here.
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 34,
    getItemKey: (i) => tableRows[i]?.id ?? i,
    overscan: 12,
  });
  const items = virtualizer.getVirtualItems();
  const padTop = items[0]?.start ?? 0;
  const padBottom = virtualizer.getTotalSize() - (items.at(-1)?.end ?? 0);

  // Roving focus: one row is tabbable; j/k/↑/↓ move it, scrolling virtual rows into view.
  const [active, setActive] = useState(0);
  const [focusPending, setFocusPending] = useState(false);
  const activeIndex = Math.min(active, Math.max(tableRows.length - 1, 0));
  // Runs after every render on purpose: the target row may only mount once the virtualizer has
  // scrolled, so this retries until it exists, then clears the flag.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!focusPending) return;
    const el = scrollRef.current?.querySelector<HTMLElement>(`tr[data-index="${activeIndex}"]`);
    if (el) {
      el.focus();
      setFocusPending(false);
    }
  });
  const moveTo = (i: number) => {
    const next = Math.max(0, Math.min(tableRows.length - 1, i));
    setActive(next);
    virtualizer.scrollToIndex(next, { align: "auto" });
    setFocusPending(true);
  };

  const colCount = table.getAllLeafColumns().length;
  // Swipe left on a row opens its drawer (phones; a tap does too).
  const touch = useRef<{ x: number; y: number } | null>(null);

  return (
    <section aria-labelledby="results-h" className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 id="results-h" className="text-section font-semibold text-ink-soft">
          Results
        </h2>
        <p className="num text-meta text-muted" aria-live="polite">
          {rows.length < total ? `Showing the first ${formatCount(rows.length)} of ${formatCount(total)}` : `${formatCount(total)} ${total === 1 ? "company" : "companies"}`}
        </p>
        {pending && (
          <span role="status" data-testid="results-pending" className="text-meta text-forest">
            Updating…
          </span>
        )}
        <div className="ml-auto">{actions}</div>
      </div>
      <div
        ref={scrollRef}
        className={`fade-x-end max-h-[70dvh] overflow-auto rounded-panel bg-paper transition-opacity duration-200 ${pending ? "opacity-50" : ""}`}
        data-testid="results-scroll"
      >
        <table className="w-full border-collapse text-cell" aria-rowcount={tableRows.length + 1}>
          <thead className="sticky top-0 z-20 bg-dune text-left text-meta text-muted">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="h-row">
                {group.headers.map((h) => {
                  const { def, kind } = h.column.columnDef.meta as Meta;
                  const sortable = kind === "value" || kind === "ticker" || kind === "flags" || kind === "coverage";
                  const sorted = sort.by === h.column.id ? sort.dir : null;
                  const label = kind === "flags" ? "Flags" : kind === "coverage" ? "Coverage" : def.label;
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : sortable ? "none" : undefined}
                      className={`px-cell font-medium whitespace-nowrap ${def.numeric || kind === "flags" || kind === "coverage" ? "text-right" : ""} ${
                        kind === "ticker" ? "sticky-col sticky left-0 z-10 bg-dune" : ""
                      }`}
                    >
                      {sortable ? (
                        <button
                          type="button"
                          onClick={() => onSort(h.column.id, def.numeric || kind === "flags" || kind === "coverage")}
                          className={`inline-flex items-center gap-1 rounded-control hover:text-ink-soft ${sorted ? "text-ink-soft" : ""}`}
                        >
                          <HeaderLabel def={def} text={kind === "flags" ? "Flags" : kind === "coverage" ? "Coverage" : def.label} srText={label} />
                          <IconSwap name={sorted === "asc" ? "arrow-up" : sorted === "desc" ? "arrow-down" : null} names={["arrow-up", "arrow-down"]} weight={500} />
                        </button>
                      ) : (
                        def.label
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 && (
              <tr aria-hidden style={{ height: padTop }}>
                <td colSpan={colCount} />
              </tr>
            )}
            {items.map((item) => {
              const row = tableRows[item.index];
              if (!row) return null;
              const r = row.original;
              return (
                <tr
                  key={row.id}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  aria-rowindex={item.index + 2}
                  aria-selected={selected === r.ticker}
                  tabIndex={item.index === activeIndex ? 0 : -1}
                  onFocus={() => setActive(item.index)}
                  onClick={() => {
                    setActive(item.index);
                    onOpen(r.ticker);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onOpen(r.ticker);
                    else if (e.key === "o" && onOpenPage) onOpenPage(r.ticker);
                    else if (e.key === "x" && onPin) onPin(r.ticker);
                    else if (e.key === "j" || e.key === "ArrowDown") moveTo(item.index + 1);
                    else if (e.key === "k" || e.key === "ArrowUp") moveTo(item.index - 1);
                    else if (e.key === "Home") moveTo(0);
                    else if (e.key === "End") moveTo(tableRows.length - 1);
                    else return;
                    e.preventDefault();
                  }}
                  onTouchStart={(e) => {
                    const t = e.touches[0];
                    touch.current = t ? { x: t.clientX, y: t.clientY } : null;
                  }}
                  onTouchEnd={(e) => {
                    const t = e.changedTouches[0];
                    const start = touch.current;
                    touch.current = null;
                    if (t && start && start.x - t.clientX > 48 && Math.abs(t.clientY - start.y) < 32) onOpen(r.ticker);
                  }}
                  onMouseEnter={() => setHovered(r.cik)}
                  onMouseLeave={() => setHovered((h) => (h === r.cik ? null : h))}
                  className={`group h-row cursor-pointer border-t border-line hover:bg-row-hover focus-visible:bg-dune aria-selected:bg-dune aria-selected:shadow-[inset_3px_0_0_var(--purple)] ${
                    freshTickers.has(r.ticker) ? "entered" : ""
                  }`}
                >
                  {row.getAllCells().map((cell) => {
                    const { def, kind } = cell.column.columnDef.meta as Meta;
                    const v = r.values[cell.column.id];
                    const note = r.notes[cell.column.id];
                    switch (kind) {
                      case "index":
                        return (
                          <td key={cell.id} className="num w-10 px-cell text-right text-muted">
                            {formatCount(r.rank ?? item.index + 1)}
                          </td>
                        );
                      case "ticker":
                        return (
                          <th
                            key={cell.id}
                            scope="row"
                            className="sticky-col num sticky left-0 z-10 bg-paper px-cell text-left font-semibold whitespace-nowrap text-forest group-hover:bg-row-hover group-focus-visible:bg-dune group-aria-selected:bg-dune"
                          >
                            {r.ticker}
                            {pinned.includes(r.ticker) && (
                              <span className="ml-1 text-meta text-forest" title="Pinned for comparison">
                                <Icon name="pin" label="pinned" />
                              </span>
                            )}
                          </th>
                        );
                      case "flags":
                        return (
                          <td key={cell.id} className="px-cell text-right">
                            {typeof v === "number" ? (
                              <span className={`num ${v > 0 ? "text-caution" : "text-muted"}`} title={`${formatCount(v)} active flags: open the row to read them`}>
                                {formatCount(v)}
                              </span>
                            ) : (
                              <NullValue note={note} />
                            )}
                          </td>
                        );
                      case "coverage":
                        return (
                          <td key={cell.id} className="px-cell text-right">
                            {typeof v === "number" ? (
                              <span className="num" title={`Coverage: ${def.definition ?? ""}`}>{formatValue("frac", v)}</span>
                            ) : (
                              <NullValue note={note} />
                            )}
                          </td>
                        );
                      default: {
                        const id = cell.column.id;
                        const crisp = screened.has(id) || id === "rank_score" || id === "market_cap";
                        if (id === "name") {
                          return (
                            <td key={cell.id} className={`${compact ? "max-w-[9rem]" : "max-w-64"} truncate px-cell whitespace-nowrap font-words text-ink-soft`} title={r.name}>
                              {displayName(r.name)}
                            </td>
                          );
                        }
                        const p = canHover && def.numeric && screened.has(id) && hovered === r.cik && percentile ? percentile(id, r.cik) : null;
                        return (
                          <td
                            key={cell.id}
                            className={`relative px-cell whitespace-nowrap ${def.numeric ? `num text-right ${crisp ? "font-medium text-ink" : "text-ink-soft"}` : "font-words text-ink-soft"}`}
                          >
                            <MetricValue def={def} value={v} note={note} slot={def.numeric} />
                            {p !== null && (
                              <span aria-hidden className="absolute right-cell bottom-1 left-cell h-0.5 rounded-full bg-line" title={`Sector percentile p${Math.round(p * 100)}`}>
                                <span className="absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-forest" style={{ left: `${p * 100}%` }} />
                              </span>
                            )}
                          </td>
                        );
                      }
                    }
                  })}
                </tr>
              );
            })}
            {padBottom > 0 && (
              <tr aria-hidden style={{ height: padBottom }}>
                <td colSpan={colCount} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
});

/** Header text; when it's an abbreviation or icon, screen readers get the full label instead. */
function HeaderLabel({ def, text, srText }: { def: ColumnDef; text: string; srText: string }) {
  const body =
    text === srText ? (
      text
    ) : (
      <>
        <span aria-hidden>{text}</span>
        <span className="sr-only">{srText}</span>
      </>
    );
  if (!def.definition) return <span>{body}</span>;
  const legend = def.numeric ? " — means the filings don't have a value; n/m means it isn't meaningful here (for example, a ratio with a negative denominator)." : "";
  return (
    <Tooltip tip={`${def.label}: ${def.definition}${legend}`} side="bottom">
      {body}
    </Tooltip>
  );
}
