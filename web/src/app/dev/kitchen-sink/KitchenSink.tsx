"use client";

import { Icon } from "@/components/ui/Icon";
import { useState, useSyncExternalStore, type ReactNode } from "react";
import { FadeScroller } from "@/components/ui/FadeScroller";
import { type IconName } from "@/components/ui/Icon";
import { IconSwap } from "@/components/ui/IconSwap";
import { Button, IconButton } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { Histogram, type Distribution } from "@/components/ui/Histogram";
import { MetricValue } from "@/components/ui/MetricValue";
import { SieveBar, type FunnelStep } from "@/components/ui/SieveBar";
import { Tooltip } from "@/components/ui/Tooltip";
import { formatCount, formatValue, type Unit } from "@/lib/format";
import type { CellNote } from "@/lib/notes";

// The living reference for the Visual standard (docs/glint-ui-upgrade.md) and docs/ui-spec.md.
// Hand-written samples in storage units, rendered through format.ts like real data. Tickers
// start with SYN and names are obviously fake (SPEC §3.3 mock rules).

const STEPS: FunnelStep[] = [
  { index: 0, label: "Universe", filter_path: null, remaining: 4812, removed: 0, removed_missing: 0, binding: false },
  { index: 1, label: `ROIC ≥ ${formatValue("frac", 0.15)}`, filter_path: ["filters", 0], remaining: 1104, removed: 3708, removed_missing: 2777, binding: true },
  { index: 2, label: `FCF yield ≥ ${formatValue("frac", 0.05)}`, filter_path: ["filters", 1], remaining: 287, removed: 817, removed_missing: 96, binding: false },
  { index: 3, label: `Net debt / EBITDA ≤ ${formatValue("x", 2)}`, filter_path: ["filters", 2], remaining: 164, removed: 123, removed_missing: 0, binding: false },
];

// ROIC-like sample: 30 bins over p1–p99, plus tails and companies with no value.
const COUNTS = [3, 6, 9, 15, 21, 34, 48, 70, 96, 130, 170, 215, 260, 300, 340, 372, 390, 380, 360, 330, 300, 265, 230, 200, 170, 140, 120, 100, 84, 70];
const DIST: Distribution = {
  metric: "roic",
  lo: -0.2,
  hi: 0.55,
  bins: COUNTS.map((count, i) => ({ lo: -0.2 + i * 0.025, hi: -0.2 + (i + 1) * 0.025, count })),
  underflow: 41,
  overflow: 38,
  min: -179.19,
  max: 5.759,
  count: 5268,
  missing: 2777,
  notMeaningful: 112,
  median: 0.081,
};

type ColKey = "market_cap" | "roic" | "fcf_yield" | "pe_ttm" | "operating_margin_change_yoy";
type Cell = { v: number | null; note?: CellNote };
type Row = { ticker: string; name: string; sector: string; cells: Record<ColKey, Cell>; flags: number; entered?: boolean };

const n = (v: number): Cell => ({ v });
const nul = (code: CellNote["code"], message: string): Cell => ({ v: null, note: { code, message } });

const ROWS: Row[] = [
  { ticker: "SYNA", name: "Synthetic Alpha Holdings", sector: "Technology", flags: 0,
    cells: { market_cap: n(12.4e9), roic: n(0.312), fcf_yield: n(0.061), pe_ttm: n(18.4), operating_margin_change_yoy: n(0.023) } },
  { ticker: "SYNB", name: "Synthetic Beta Industrial", sector: "Industrials", flags: 2, entered: true,
    cells: { market_cap: n(3.1e9), roic: { v: 0.228, note: { code: "ASSUMED_TAX_RATE", message: "No income tax line; used 21%." } }, fcf_yield: n(0.074), pe_ttm: n(14.2), operating_margin_change_yoy: n(-0.011) } },
  { ticker: "SYNC", name: "Synthetic Gamma Bancorp", sector: "Banks", flags: 0,
    cells: { market_cap: n(842e6), roic: nul("NOT_APPLICABLE_SECTOR", "ROIC isn't meaningful for banks."), fcf_yield: n(0.09), pe_ttm: n(9.8), operating_margin_change_yoy: nul("NOT_APPLICABLE_SECTOR", "Operating margin isn't defined for banks.") } },
  { ticker: "SYND", name: "Synthetic Delta Therapeutics", sector: "Health Care", flags: 1,
    cells: { market_cap: n(1.96e9), roic: n(0.175), fcf_yield: n(0.052), pe_ttm: nul("NEGATIVE_DENOMINATOR", "Net income (TTM) is negative."), operating_margin_change_yoy: n(0.068) } },
];

// Screened columns are crisp; the rest are soft (Visual standard: reading comfort).
const COLUMNS: { key: ColKey; unit: Unit; label: string; screened: boolean }[] = [
  { key: "market_cap", unit: "usd", label: "Market cap", screened: true },
  { key: "roic", unit: "frac", label: "ROIC", screened: true },
  { key: "fcf_yield", unit: "frac", label: "FCF yield", screened: true },
  { key: "pe_ttm", unit: "x", label: "P/E", screened: false },
  { key: "operating_margin_change_yoy", unit: "pp", label: "Op. margin change", screened: false },
];

const SWATCHES: [string, string][] = [
  ["sand", "bg-sand"], ["paper", "bg-paper"], ["dune", "bg-dune"], ["ink", "bg-ink"], ["ink-soft", "bg-ink-soft"],
  ["muted", "bg-muted"], ["forest", "bg-forest"], ["sand-soft", "bg-sand-soft"], ["purple", "bg-purple"],
  ["purple-ink", "bg-purple-ink"], ["pos", "bg-pos"], ["neg", "bg-neg"], ["caution", "bg-caution"], ["nodata", "hatch"],
  ["line", "bg-line"], ["line-strong", "bg-line-strong"],
];

/** The token's value as the stylesheet defines it (OKLCH), read live so it can't drift. */
function TokenValue({ name }: { name: string }) {
  const v = useSyncExternalStore(
    () => () => {},
    () => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim(),
    () => "",
  );
  return <p className="font-code text-meta text-muted">{v}</p>;
}

const ICONS: IconName[] = ["close", "chevron-right", "chevron-down", "info", "check", "cross", "arrow-up", "arrow-down", "caret-up", "caret-down", "lock", "search", "download", "link", "warning"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3" aria-labelledby={`ks-${title}`}>
      <h2 id={`ks-${title}`} className="text-section font-semibold text-ink-soft">
        {title}
      </h2>
      {children}
    </section>
  );
}

export function KitchenSink() {
  const [drawerRow, setDrawerRow] = useState<Row | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pressed, setPressed] = useState(true);
  const [threshold, setThreshold] = useState(0.15);
  const [copied, setCopied] = useState(false);
  const [universe, setUniverse] = useState(["Operating companies only", `Trades at least ${formatValue("usd", 1e6)} a day`]);

  return (
    <main className="mx-auto max-w-6xl space-y-10 px-4 py-6">
      <div className="space-y-1">
        <h1 className="text-title font-semibold text-ink">Kitchen sink</h1>
        <p className="max-w-prose text-prose">Every value here is a hand-written sample, drawn with the same tokens and formatters as the app.</p>
      </div>

      <Section title="Colour tokens">
        <p className="text-meta text-muted">Values as the browser computed them. The stylesheet declares OKLCH; the CSS build may serve it as Lab, which renders the same.</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
          {SWATCHES.map(([name, cls]) => (
            <div key={name} className="space-y-1">
              <div className={`h-10 rounded-panel border border-line ${cls}`} />
              <p className="text-meta text-ink-soft">{name}</p>
              <TokenValue name={name} />
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type">
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <p className="text-title font-semibold text-ink">Quality compounders</p>
            <p className="text-section font-semibold text-ink-soft">Section title</p>
            <p className="max-w-prose text-prose">
              Prose in Atkinson Hyperlegible Next: companies that pass the universe and every filter, with the reasons the rest didn&apos;t.
            </p>
            <p className="text-label">Label: Fiscal year ends Nov 30. Latest 10-K filed 15 Jan 2025.</p>
            <p className="text-meta text-muted">Meta: filings as of 2 Jan 2026.</p>
          </div>
          <div className="space-y-2">
            <p className="num text-figure font-semibold text-ink">$512.40 and $221B</p>
            <p className="num text-cell font-semibold text-forest">ADBE SYNA SYNB</p>
            <p className="num text-cell text-ink-soft">{[1104, 287, 164, 58].map(formatCount).join("  ")}</p>
            <p className="font-code text-meta text-muted">roic = nopat_ttm / avg(invested_capital)</p>
            <p className="text-label">Look-alikes: Il1 O0 rn m</p>
          </div>
        </div>
      </Section>

      <Section title="Icons">
        <div className="space-y-2">
          {([400, 500, 600] as const).map((w) => (
            <p key={w} className={`flex flex-wrap items-center gap-3 text-section text-ink-soft ${w === 400 ? "font-normal" : w === 500 ? "font-medium" : "font-semibold"}`}>
              <span className="w-24">Weight {w}</span>
              {ICONS.map((n) => (
                <Icon key={n} name={n} weight={w} label={n} />
              ))}
            </p>
          ))}
          <p className="flex items-center gap-2 text-label">
            <Button onClick={() => setCopied((c) => !c)}>
              <IconSwap name={copied ? "check" : "link"} names={["link", "check"]} /> {copied ? "Copied" : "Share"}
            </Button>
            <span className="text-meta text-muted">The outgoing icon blurs as it fades.</span>
          </p>
        </div>
      </Section>

      <Section title="Edges and corners">
        <FadeScroller className="flex gap-2 rounded-panel bg-paper p-panel">
          {Array.from({ length: 16 }, (_, k) => (
            <span key={k} className="num shrink-0 rounded-control border border-line-strong px-3 py-1 text-label">
              Stage {k + 1}
            </span>
          ))}
        </FadeScroller>
        <div className="max-w-sm rounded-sheet bg-paper p-[var(--pad-sheet)] shadow-overlay">
          <div className="rounded-in-sheet bg-dune p-panel text-label">Inner radius = 8px sheet − 8px padding = 0.</div>
        </div>
      </Section>

      <Section title="Buttons and chips">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Apply preset</Button>
          <Button>Add filter</Button>
          <Button variant="ghost">Reset</Button>
          <Button disabled>Disabled</Button>
          <IconButton label="Remove filter">
            <Icon name="close" />
          </IconButton>
        </div>
        <div className="flex flex-wrap items-center gap-2" aria-label="Universe">
          {universe.map((u) => (
            <Chip key={u} onRemove={() => setUniverse((xs) => xs.filter((x) => x !== u))} removeLabel={`Remove universe rule ${u}`}>
              {u}
            </Chip>
          ))}
          <Chip locked lockReason="Glint only screens companies with XBRL financials.">
            Has XBRL financials
          </Chip>
          <Chip pressed={pressed} onToggle={() => setPressed((p) => !p)}>
            ROIC misses, 3
          </Chip>
          <Tooltip tip="Tooltips open on hover and on keyboard focus.">
            <span className="text-label text-forest underline decoration-dotted underline-offset-2">Focus me</span>
          </Tooltip>
        </div>
      </Section>

      <Section title="Sieve">
        <SieveBar steps={STEPS} onSelect={(s) => setSelected(s.label)} />
        <p className="text-meta text-muted" aria-live="polite">
          {selected ? `Selected: ${selected}` : "Select a stage to see what it removed."}
        </p>
      </Section>

      <Section title="Histogram">
        <div className="max-w-sm rounded-panel bg-paper p-panel">
          <Histogram
            dist={DIST}
            threshold={threshold}
            cmp="gte"
            unit="frac"
            label="ROIC distribution in the universe"
            onThreshold={setThreshold}
            caption={<p className="text-meta text-muted">Drag the handle, or focus it and use the arrow keys (Shift for ten bins).</p>}
          />
        </div>
      </Section>

      <Section title="Results table">
        <div className="overflow-x-auto rounded-panel bg-paper">
          <table className="w-full min-w-[760px] border-collapse text-cell">
            <thead className="bg-dune text-left text-head text-muted">
              <tr className="h-row">
                <th scope="col" className="sticky left-0 z-10 bg-dune px-cell font-medium">Ticker</th>
                <th scope="col" className="px-cell font-medium">Name</th>
                <th scope="col" className="px-cell font-medium">Sector</th>
                {COLUMNS.map((c) => (
                  <th key={c.key} scope="col" aria-sort={c.key === "market_cap" ? "descending" : "none"} className="px-cell text-right font-medium">
                    {c.label}
                    {c.key === "market_cap" && <Icon name="arrow-down" weight={500} className="ml-0.5" />}
                  </th>
                ))}
                <th scope="col" className="px-cell text-right font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => (
                <tr
                  key={r.ticker}
                  tabIndex={0}
                  onClick={() => setDrawerRow(r)}
                  onKeyDown={(e) => e.key === "Enter" && setDrawerRow(r)}
                  className={`group h-row cursor-pointer border-t border-line hover:bg-dune/50 focus-visible:bg-dune ${r.entered ? "entered" : ""}`}
                >
                  <th scope="row" className="sticky left-0 bg-paper px-cell text-left font-semibold text-forest group-hover:bg-dune">
                    {r.ticker}
                  </th>
                  <td className="max-w-56 truncate px-cell font-words text-ink-soft">{r.name}</td>
                  <td className="px-cell font-words text-ink-soft">{r.sector}</td>
                  {COLUMNS.map((c) => (
                    <td key={c.key} className={`num px-cell text-right ${c.screened ? "font-medium text-ink" : "text-ink-soft"}`}>
                      <MetricValue def={{ id: c.key, unit: c.unit }} value={r.cells[c.key].v} note={r.cells[c.key].note} />
                    </td>
                  ))}
                  <td className={`num px-cell text-right ${r.flags > 0 ? "text-caution" : "text-muted"}`}>{formatCount(r.flags)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-meta text-muted">SYNB entered because of an edit: a purple bar that fades (static with reduced motion).</p>
      </Section>

      <Section title="States">
        <div className="grid gap-4 md:grid-cols-3">
          <div className="space-y-2 rounded-panel bg-paper p-panel" role="status" aria-busy="true" aria-label="Loading example">
            {[0, 1, 2].map((k) => (
              <div key={k} className="h-row animate-pulse rounded-control bg-dune/60" />
            ))}
          </div>
          <div className="space-y-2 rounded-panel bg-paper p-panel">
            <p className="text-prose">No company passes all 4 filters. Lowering FCF yield to 4.8% adds 1 company.</p>
            <Button variant="primary">Lower FCF yield to 4.8%</Button>
          </div>
          <div role="alert" className="space-y-2 rounded-panel border-l-2 border-neg bg-paper p-panel">
            <p className="text-prose">Glint can&apos;t reach its API, so these results may be out of date.</p>
            <Button>Retry</Button>
          </div>
        </div>
      </Section>

      <Drawer
        open={drawerRow !== null}
        onClose={() => setDrawerRow(null)}
        title={
          drawerRow && (
            <>
              <span className="num font-semibold text-forest">{drawerRow.ticker}</span> <span className="text-ink">{drawerRow.name}</span>
            </>
          )
        }
        subtitle={drawerRow && `${drawerRow.sector}, NYSE`}
      >
        {drawerRow && (
          <div className="space-y-6">
            <section className="space-y-2" aria-label="Metrics">
              <h3 className="text-section font-semibold text-ink-soft">This screen&apos;s metrics</h3>
              <dl className="divide-y divide-line">
                {COLUMNS.map((c) => (
                  <div key={c.key} className="flex items-center justify-between py-1.5">
                    <dt className="text-label text-ink-soft">{c.label}</dt>
                    <dd className={`num text-cell ${c.screened ? "font-medium text-ink" : "text-ink-soft"}`}>
                      <MetricValue def={{ id: c.key, unit: c.unit }} value={drawerRow.cells[c.key].v} note={drawerRow.cells[c.key].note} />
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
            <section className="space-y-2" aria-label="Flags">
              <h3 className="text-section font-semibold text-ink-soft">Flags</h3>
              <div className="border-l-2 border-caution pl-3">
                <p className="max-w-prose text-prose">Share count is up {formatValue("frac", 0.072)} in a year. What&apos;s driving the dilution?</p>
              </div>
            </section>
          </div>
        )}
      </Drawer>
    </main>
  );
}
