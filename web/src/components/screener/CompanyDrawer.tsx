"use client";

import Link from "next/link";
import { memo, useEffect, useMemo, useRef } from "react";
import { CompanyView } from "@/components/company/CompanyView";
import { Figures } from "@/components/company/Figures";
import { Button, IconButton } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { Icon } from "@/components/ui/Icon";
import { useCompany, useMetrics } from "@/lib/api/hooks";
import { formatCount } from "@/lib/format";
import { displayName } from "@/lib/names";
import { encodeScreen } from "@/lib/screen/codec";
import type { Screen } from "@/lib/screen/types";

/**
 * The company drawer, built for flicking through results (docs/ui-spec.md §4.5): the header has
 * the facts you scan for (ticker, name, price, market cap, sector, the screen check), j/k or ↑/↓
 * move to the next or previous result in place, and details sit lower down or collapsed.
 */
export const CompanyDrawer = memo(function CompanyDrawer({
  ticker,
  screen,
  onClose,
  order = [],
  onNavigate,
  pinned = [],
  onPin,
}: {
  ticker: string | null;
  screen: Screen | null;
  onClose: () => void;
  /** Result tickers in table order, for j/k and "12 of 139". */
  order?: readonly string[];
  onNavigate?: (ticker: string) => void;
  pinned?: readonly string[];
  onPin?: (ticker: string) => void;
}) {
  const company = useCompany(ticker, screen);
  const metrics = useMetrics();
  const defs = useMemo(() => new Map((metrics.data?.metrics ?? []).map((m) => [m.id, m])), [metrics.data]);
  const c = company.data?.company;
  const same = c && ticker && c.tickers.some((t) => t.toUpperCase() === ticker.toUpperCase());
  const pageHref = useMemo(
    () => (ticker ? `/company/${encodeURIComponent(ticker)}${screen?.filters?.children?.length ? `?s=${encodeScreen(screen)}` : ""}` : "#"),
    [ticker, screen],
  );
  const index = ticker ? order.indexOf(ticker) : -1;
  const step = (dir: 1 | -1) => {
    if (index < 0 || !onNavigate) return;
    const next = order[index + dir];
    if (next) onNavigate(next);
  };
  const isPinned = ticker ? pinned.includes(ticker) : false;
  // "x" inside the open drawer pins or unpins its company (the table's rows do the same).
  const pinRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    pinRef.current = ticker && onPin ? () => onPin(ticker) : null;
  });
  useEffect(() => {
    if (ticker === null) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      const typing = t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName));
      if (e.key !== "x" || typing || e.metaKey || e.ctrlKey || e.altKey || !(t instanceof Element && t.closest('[role="dialog"]:not([data-compare])'))) return;
      e.preventDefault();
      pinRef.current?.();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ticker]);
  const data = same ? company.data : undefined;

  return (
    <Drawer
      open={ticker !== null}
      onClose={onClose}
      onStep={order.length > 1 ? step : undefined}
      title={
        <>
          <span className="num text-title font-semibold text-forest">{ticker}</span>{" "}
          <span className="text-section text-ink">{data ? displayName(data.company.name) : null}</span>
        </>
      }
      subtitle={data ? [data.company.sector, data.company.exchange].filter(Boolean).join(", ") : null}
      actions={
        ticker && (
          <>
            {onPin && (
              <IconButton label={isPinned ? `Unpin ${ticker}` : `Pin ${ticker} for comparison (x)`} onClick={() => onPin(ticker)} className={isPinned ? "text-forest" : ""}>
                <Icon name="pin" weight={isPinned ? 600 : 400} />
              </IconButton>
            )}
            <Link href={pageHref} className="inline-flex h-ctl items-center rounded-control px-2 text-label text-forest underline underline-offset-2">
              Full page
            </Link>
          </>
        )
      }
      header={data ? <Figures data={data} defs={defs} screen={screen} /> : null}
      footer={
        order.length > 0 && index >= 0 ? (
          <div className="flex items-center gap-2">
            <span className="num text-label text-ink-soft" aria-live="polite">
              <span className="sr-only">
                {ticker}, {data ? displayName(data.company.name) : ""},{" "}
              </span>
              {formatCount(index + 1)} of {formatCount(order.length)}
            </span>
            <span className="text-meta text-muted">j / k to move</span>
            <span className="ml-auto flex gap-1">
              <Button onClick={() => step(-1)} disabled={index <= 0} aria-label="Previous result">
                <Icon name="arrow-up" />
              </Button>
              <Button onClick={() => step(1)} disabled={index >= order.length - 1} aria-label="Next result">
                <Icon name="arrow-down" />
              </Button>
            </span>
          </div>
        ) : null
      }
    >
      {company.error ? (
        <p role="alert" className="text-label text-neg">
          {company.error.message}
        </p>
      ) : !data || !metrics.data ? (
        <div className="space-y-2" role="status" aria-label="Loading company">
          {Array.from({ length: 6 }, (_, k) => (
            <div key={k} className="h-6 animate-pulse rounded-panel bg-dune" />
          ))}
        </div>
      ) : (
        <CompanyView data={data} metrics={metrics.data.metrics} screen={screen} variant="drawer" />
      )}
    </Drawer>
  );
});
