"use client";

import { Icon } from "@/components/ui/Icon";
import dynamic from "next/dynamic";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { Figures } from "./Figures";
import { displayName } from "@/lib/names";
import { CATEGORY_LABEL } from "@/lib/labels";
import { MetricValue } from "@/components/ui/MetricValue";
import { NullValue } from "@/components/ui/NullValue";
import { PercentileTick } from "@/components/ui/PercentileTick";
import { MetricTip } from "@/components/ui/MetricTip";
import { metricHref } from "@/lib/metricText";
import Link from "next/link";
import { InfoTip, Tooltip } from "@/components/ui/Tooltip";
import type { components } from "@/lib/api/types";
import { evidenceLabel, formatEvidence, sourceHref } from "@/lib/company";
import { describePercentile, formatCount, formatDate, formatDateTimeEt, formatFiscalYearEnd } from "@/lib/format";
import { describeNode } from "@/lib/screen/describe";
import { nodeAtPath } from "@/lib/screen/funnel";
import { screenCheck } from "@/lib/screen/check";
import { isGroup, type Condition, type Group, type MetricDefinition, type Screen } from "@/lib/screen/types";

type Company = components["schemas"]["CompanyResponse"];
type Category = components["schemas"]["Category"];
type Kind = components["schemas"]["Kind"];

// Recharts only loads with the drawer or company page, never with the table.
const Sparklines = dynamic(() => import("./Sparklines"), {
  ssr: false,
  loading: () => <div className="h-24 animate-pulse rounded-panel bg-dune" role="status" aria-label="Loading charts" />,
});

const DRAWER_OPEN: Category[] = ["size_liquidity", "valuation", "profitability"];
const KIND_LABEL: Record<Kind, string> = { spac: "SPAC", fund: "Fund", shell: "Shell company", no_common_equity: "No listed common stock", synthetic: "Synthetic", operating: "Operating" };

/** SPEC §2.9 company view: the drawer body and the /company/[ticker] page. Display only. */
// Section headings sit one level under the company's own: h2 on the page (under its h1), h3 in
// the drawer (under the drawer's h2 title).
const SectionLevel = createContext<2 | 3>(3);

function SectionHeading({ className, children }: { className: string; children: ReactNode }) {
  const H = useContext(SectionLevel) === 2 ? "h2" : "h3";
  return <H className={className}>{children}</H>;
}

export function CompanyView({
  data,
  metrics,
  screen,
  variant,
  stats,
  screened,
  extraFlags,
}: {
  data: Company;
  metrics: MetricDefinition[];
  /** The screen the company was opened from, to label why_passed. */
  screen: Screen | null;
  variant: "drawer" | "page";
  /** Sector median and percentile for a metric (from the build's columns), when loaded. */
  stats?: (metric: string) => { median: number | null; percentile: number | null } | null;
  /** Metrics the screen filters or ranks on: highlighted in the metric groups. */
  screened?: ReadonlySet<string>;
  /** More flag rows (red-flag presets this company trips). */
  extraFlags?: ReactNode;
}) {
  const defs = useMemo(() => new Map(metrics.map((m) => [m.id, m])), [metrics]);
  const c = data.company;

  return (
    <SectionLevel.Provider value={variant === "page" ? 2 : 3}>
    <div className="space-y-6 text-label">
      {variant === "page" && <Header data={data} defs={defs} screen={screen} />}

      {data.why_passed && data.why_passed.length > 0 && screen ? (
        <ScreenCheckSection outcomes={data.why_passed} screen={screen} defs={defs} cells={data.metrics} sector={c.sector} verdictInHeader />
      ) : (
        <KeyMetrics data={data} defs={defs} />
      )}

      <Section title="Flags">
        {extraFlags}
        {data.flags.length === 0 ? (
          <p className="text-ink-soft">No flags raised.</p>
        ) : (
          <ul className="space-y-2">
            {data.flags.map((f) => (
              <li key={f.flag_id} className={`border-l-2 py-1 pl-3 ${f.severity === "caution" ? "border-caution" : "border-line-strong"}`}>
                <p className="max-w-prose text-prose text-ink-soft">{f.question}</p>
                {Object.keys(f.evidence).length > 0 && (
                  <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-meta">
                    {Object.entries(f.evidence).map(([k, v]) => (
                      <EvidenceRow key={k} label={evidenceLabel(k, defs)} value={formatEvidence(k, v, defs)} />
                    ))}
                  </dl>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="History" note="Last 10 fiscal years and last 12 trailing-twelve-month points.">
        <Sparklines history={data.history} metrics={defs} />
      </Section>

      {variant === "drawer" ? (
        <Collapsible title="All metrics">
          <MetricsByCategory data={data} metrics={metrics} variant={variant} />
        </Collapsible>
      ) : (
        <Section title="All metrics" note="Hover or focus a name for its formula, basis and unit. Each row shows the sector median and where the company sits in its sector.">
          <MetricsByCategory data={data} metrics={metrics} variant={variant} stats={stats} screened={screened} />
        </Section>
      )}

      {variant === "drawer" ? (
        <Collapsible title="Company details">
          <p className="text-label text-ink">{c.name}</p>
          <Facts data={data} />
        </Collapsible>
      ) : (
        <Section title="Company details">
          <p className="text-label text-ink">{c.name}</p>
          <Facts data={data} />
        </Section>
      )}

      <Section title="Sources" note="The filings this build used.">
        {data.sources.length === 0 ? (
          <p className="text-muted">No filings recorded.</p>
        ) : (
          <ul className="space-y-1">
            {data.sources.map((s) => {
              const href = sourceHref(s.url);
              return (
                <li key={s.accn} className="flex flex-wrap items-baseline gap-x-3">
                  <span className="w-14 text-muted">{s.form ?? <Tooltip tip="The build doesn't record this filing's form type.">—</Tooltip>}</span>
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer noopener" className="font-code text-meta text-forest underline underline-offset-2">
                      {s.accn}
                      <span className="sr-only"> (opens SEC EDGAR in a new tab)</span>
                    </a>
                  ) : (
                    <span className="font-code text-meta text-muted" title="Not an SEC EDGAR link (synthetic data)">
                      {s.accn}
                    </span>
                  )}
                  <span className="text-meta text-muted">filed {formatDate(s.filed)}</span>
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-meta text-muted">
          CIK <span className="font-code">{c.cik}</span>
        </p>
      </Section>
    </div>
    </SectionLevel.Provider>
  );
}

function Header({ data, defs, screen }: { data: Company; defs: Map<string, MetricDefinition>; screen: Screen | null }) {
  const c = data.company;
  return (
    <header className="space-y-3">
      <div className="space-y-1">
        <h1 className="text-title font-semibold text-ink">
          <span className="num text-forest">{c.primary_ticker ?? c.tickers[0] ?? c.cik}</span> {displayName(c.name)}
        </h1>
        <p className="text-label text-ink-soft">{[c.sector, c.exchange].filter(Boolean).join(", ")}</p>
      </div>
      <Figures data={data} defs={defs} screen={screen} />
    </header>
  );
}

function Facts({ data }: { data: Company }) {
  const c = data.company;
  // Facts that change how to read the numbers, as plain text: caution where comparability suffers.
  const notes: { text: string; caution: boolean }[] = [];
  if (c.kind !== "operating") notes.push({ text: KIND_LABEL[c.kind] ?? c.kind, caution: true });
  if (c.is_foreign_filer) notes.push({ text: "Foreign filer", caution: true });
  if (c.is_reit) notes.push({ text: "REIT", caution: false });
  if (c.reporting_currency && c.reporting_currency !== "USD") notes.push({ text: `Reports in ${c.reporting_currency}`, caution: true });
  if (!c.has_facts) notes.push({ text: "No XBRL facts", caution: true });
  return (
    <div className="space-y-2">
      {(c.tickers.length > 1 || notes.length > 0) && (
        <p className="text-label text-ink-soft">
          {c.tickers.length > 1 && <span>Listed as {c.tickers.join(", ")}. </span>}
          {notes.map((n, i) => (
            <span key={n.text} className={n.caution ? "text-caution" : undefined}>
              {n.text}
              {i < notes.length - 1 ? ", " : "."}
            </span>
          ))}
        </p>
      )}
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5 text-meta">
        <Fact label="Sector">
          {c.sector}
          {c.sic !== null && <span className="text-muted">, SIC {c.sic}</span>}
        </Fact>
        <Fact label="Filer type">{c.filer_category ?? <NotRecorded />}</Fact>
        <Fact label="Fiscal year ends">{c.fiscal_year_end ? formatFiscalYearEnd(c.fiscal_year_end) : <NotRecorded />}</Fact>
        <Fact label="Latest 10-K / 10-Q">
          {c.last_annual_date ? formatDate(c.last_annual_date) : <NotRecorded />} / {c.last_quarterly_date ? formatDate(c.last_quarterly_date) : <NotRecorded />}
        </Fact>
        <Fact label="Fundamentals as of">{data.as_of.fundamentals ? formatDateTimeEt(data.as_of.fundamentals) : <NotRecorded />}</Fact>
        <Fact label="Prices as of">{data.as_of.prices ? `close of ${formatDate(data.as_of.prices)}` : <NotRecorded />}</Fact>
      </dl>
    </div>
  );
}

/** A fact the build doesn't record: "—" with a reason, never a bare dash (principle 3). */
function NotRecorded() {
  return <NullValue note={null} fallbackReason="Not recorded in this build." />;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="num">{value}</dd>
    </>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="space-y-2" aria-label={title}>
      <div className="flex items-center gap-1">
        <SectionHeading className="text-section font-semibold text-ink-soft">{title}</SectionHeading>
        {note && <InfoTip label={`About ${title.toLowerCase()}`}>{note}</InfoTip>}
      </div>
      {children}
    </section>
  );
}

/** Short names for a top-level filter: the metric, or a group's metrics joined by its operator. */
function filterName(node: Condition | Group, defs: Map<string, MetricDefinition>): string {
  if (!isGroup(node)) return defs.get(node.metric)?.name ?? (node.metric === "sector" ? "Sector" : node.metric);
  return [...new Set((node.children ?? []).map((c) => filterName(c, defs)))].join(node.op === "or" ? " or " : " and ");
}

/**
 * The screen check: the heading says what actually happened ("Passes 3 of 5", "Fails ROIC, FCF
 * margin"), never "Why it passed" above a list with failures in it.
 */
function ScreenCheckSection({
  outcomes,
  screen,
  defs,
  cells,
  sector,
  verdictInHeader = false,
}: {
  outcomes: components["schemas"]["FilterOutcome"][];
  screen: Screen;
  defs: Map<string, MetricDefinition>;
  cells: Company["metrics"];
  sector: string;
  /** The drawer shows the verdict in its header: here the section is just the screen's metrics. */
  verdictInHeader?: boolean;
}) {
  const check = screenCheck(screen, outcomes);
  const total = check.filters.length;
  const title = !check.inUniverse || total === 0 ? "Screen check" : check.failed.length === 0 ? `Passes all ${formatCount(total)}` : `Passes ${formatCount(check.passedCount)} of ${formatCount(total)}`;
  const failedNames = check.failed.map((f) => filterName(f.node, defs));
  return (
    <section className="space-y-2" aria-label="Screen check">
      {verdictInHeader ? (
        <SectionHeading className="text-section font-semibold text-ink-soft">This screen&apos;s metrics</SectionHeading>
      ) : (
      <div className="space-y-0.5">
        <SectionHeading className={`text-label font-semibold ${check.inUniverse && total > 0 ? (check.failed.length === 0 ? "text-forest" : "text-neg") : ""}`}>{title}</SectionHeading>
        {!check.inUniverse ? (
          <p className="text-meta text-muted">Outside this screen&apos;s universe, so its filters weren&apos;t checked.</p>
        ) : failedNames.length > 0 ? (
          <p className="text-meta text-neg">Fails {failedNames.join(", ")}</p>
        ) : null}
      </div>
      )}
      <WhyPassed outcomes={outcomes} screen={screen} defs={defs} cells={cells} sector={sector} />
    </section>
  );
}

function WhyPassed({
  outcomes,
  screen,
  defs,
  cells,
  sector,
}: {
  outcomes: components["schemas"]["FilterOutcome"][];
  screen: Screen | null;
  defs: Map<string, MetricDefinition>;
  /** The company's metric cells, for the reason behind a null filter value. */
  cells: Company["metrics"];
  /** The company's sector, for "better than 87% of Technology". */
  sector: string;
}) {
  // A pass is the check alone (the verdict above already says "Passes all"); a failure keeps its word.
  const anyFailed = outcomes.some((o) => !o.passed);
  return (
    <ul className="divide-y divide-line rounded-panel bg-paper">
      {outcomes.map((o) => {
        const node = screen ? nodeAtPath(screen, o.filter_path) : null;
        const label = o.filter_path[0] === "universe" ? "In the screen's universe" : node ? describeNode(node, defs) : o.label;
        const metric = node && !isGroup(node) ? node.metric : null;
        const def = metric ? (defs.get(metric) ?? { id: metric, unit: "text" as const }) : null;
        return (
          <li key={o.filter_path.join(".")} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-cell py-1.5">
            <span className={`${anyFailed ? "w-16" : "w-4"} shrink-0 text-meta font-semibold ${o.passed ? "text-forest" : "text-neg"}`}>
              <Icon name={o.passed ? "check" : "cross"} weight={600} className="mr-1" />
              {o.passed ? <span className="sr-only">Passed</span> : "Failed"}
            </span>
            <span className="min-w-0 flex-1">{label}</span>
            {def && (
              <span className="num">
                <MetricValue def={def} value={o.value} note={metric ? (cells[metric]?.note ?? null) : null} />
              </span>
            )}
            {o.sector_percentile !== null && def && (
              <PercentileTick p={o.sector_percentile} said={describePercentile(o.sector_percentile, ("better" in def ? def.better : "neutral") as "higher" | "lower" | "neutral", sector)} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

const COLLAPSED_KEY = "glint.metricGroups.collapsed";

function readCollapsed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

/**
 * All metrics by category. On the page: groups flow in CSS columns (no holes), each collapsible
 * with the choice remembered; each row has the value, the sector median and a percentile tick;
 * the screen's metrics get a forest rule. In the drawer: a plain list of groups.
 */
function MetricsByCategory({
  data,
  metrics,
  variant,
  stats,
  screened,
}: {
  data: Company;
  metrics: MetricDefinition[];
  variant: "drawer" | "page";
  stats?: (metric: string) => { median: number | null; percentile: number | null } | null;
  screened?: ReadonlySet<string>;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => (variant === "page" ? readCollapsed() : new Set()));
  const toggle = (cat: string, open: boolean) =>
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (open) next.delete(cat);
      else next.add(cat);
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
      } catch {
        // Storage blocked: the choice lasts for this page only.
      }
      return next;
    });
  const groups = new Map<Category, MetricDefinition[]>();
  for (const m of metrics) {
    if (!(m.id in data.metrics)) continue;
    const list = groups.get(m.category) ?? [];
    list.push(m);
    groups.set(m.category, list);
  }
  const anyPrice = [...groups.values()].some((list) => list.some((m) => m.tier === "price"));
  return (
    <div className="space-y-3">
      <div className={variant === "page" ? "gap-6 md:columns-2 xl:columns-3" : "space-y-2"}>
        {[...groups].map(([cat, defs]) => (
          <details
            key={cat}
            open={variant === "page" ? !collapsed.has(cat) : DRAWER_OPEN.includes(cat)}
            onToggle={variant === "page" ? (e) => toggle(cat, (e.currentTarget as HTMLDetailsElement).open) : undefined}
            className="group/g mb-4 break-inside-avoid rounded-panel bg-paper"
          >
            <summary className="flex cursor-pointer list-none items-center gap-1 px-cell py-1.5 text-label font-semibold text-ink-soft">
              <Icon name="chevron-right" className="transition-transform duration-150 group-open/g:rotate-90" />
              {CATEGORY_LABEL[cat]} <span className="num font-normal text-muted">{formatCount(defs.length)}</span>
            </summary>
            <dl className="divide-y divide-line border-t border-line">
              {defs.map((m) => {
                const cell = data.metrics[m.id];
                const st = stats?.(m.id) ?? null;
                const hot = screened?.has(m.id) ?? false;
                return (
                  <div key={m.id} className={`grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 px-cell py-1 ${hot ? "shadow-[inset_2px_0_0_var(--forest)]" : ""}`}>
                    <dt className="min-w-0 text-label text-ink-soft">
                      <Tooltip tip={<MetricTip def={m} extra={m.tier === "price" ? `price as of ${formatDate(data.as_of.prices)}` : "SEC filings"} />} side="bottom">
                        {(described) => (
                          <Link href={metricHref(m.id)} {...described} className="rounded-control underline-offset-2 hover:underline">
                            {m.name}
                          </Link>
                        )}
                      </Tooltip>
                      {m.tier === "price" && (
                        <span className="ml-1 text-meta text-muted" title="Uses the latest market price">
                          <span aria-hidden>$</span>
                          <span className="sr-only">(uses the market price)</span>
                        </span>
                      )}
                    </dt>
                    <dd className={`num text-right text-cell ${hot ? "font-medium text-ink" : "text-ink-soft"}`}>
                      <MetricValue def={m} value={cell?.value} note={cell?.note} slot />
                    </dd>
                    {variant === "page" && st && (st.median !== null || st.percentile !== null) && (
                      <dd className="col-span-2 flex items-center justify-end gap-3 pb-0.5">
                        {st.median !== null && (
                          <span className="num text-meta text-muted">
                            median <MetricValue def={m} value={st.median} note={null} />
                          </span>
                        )}
                        {st.percentile !== null && typeof cell?.value === "number" && (
                          <PercentileTick p={st.percentile} said={describePercentile(st.percentile, m.better, data.company.sector)} />
                        )}
                      </dd>
                    )}
                  </div>
                );
              })}
            </dl>
          </details>
        ))}
      </div>
      {anyPrice && <p className="text-meta text-muted">$ uses the latest market price, as of {formatDate(data.as_of.prices)}. Everything else comes from SEC filings.</p>}
    </div>
  );
}

function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group/c" aria-label={title}>
      <summary className="flex cursor-pointer list-none items-center gap-1 text-section font-semibold text-ink-soft">
        <Icon name="chevron-right" className="transition-transform duration-150 group-open/c:rotate-90" />
        {title}
      </summary>
      <div className="space-y-3 pt-2">{children}</div>
    </details>
  );
}

/** Opened without a screen: a fixed set of headline metrics instead of a screen check. */
// Market cap and price sit in the header figures, so they aren't repeated here.
export const KEY_METRICS = ["revenue_ttm", "operating_margin", "roic", "fcf_yield", "net_debt_to_ebitda"];
function KeyMetrics({ data, defs }: { data: Company; defs: Map<string, MetricDefinition> }) {
  const ids = KEY_METRICS.filter((id) => id in data.metrics);
  if (ids.length === 0) return null;
  return (
    <section className="space-y-2" aria-label="Key metrics">
      <SectionHeading className="text-section font-semibold text-ink-soft">Key metrics</SectionHeading>
      <dl className="divide-y divide-line">
        {ids.map((id) => {
          const def = defs.get(id) ?? { id, unit: "text" as const, name: id };
          const cell = data.metrics[id];
          return (
            <div key={id} className="flex items-baseline justify-between gap-3 py-1.5">
              <dt className="text-label text-ink-soft">{"name" in def ? def.name : id}</dt>
              <dd className="num text-cell text-ink-soft">
                <MetricValue def={def} value={cell?.value} note={cell?.note} />
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
