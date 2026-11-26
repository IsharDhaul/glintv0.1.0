"use client";

import { Formula } from "@/components/ui/Formula";
import { useEffect, useMemo, useState } from "react";
import { StatusBanner } from "@/components/screener/StatusBanner";
import { useMetrics } from "@/lib/api/hooks";
import type { components } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { BASIS_LABEL, CATEGORY_LABEL, plainText, SCOPE_LABEL, TIER_LABEL, UNIT_LABEL } from "@/lib/labels";
import { metricHref, splitDefinition } from "@/lib/metricText";
import { Icon } from "@/components/ui/Icon";
import { IconSwap } from "@/components/ui/IconSwap";
import type { MetricDefinition } from "@/lib/screen/types";

type Category = components["schemas"]["Category"];

/**
 * Metric dictionary (SPEC §3.1), generated from the registry the API serves: search, category
 * tabs, and for each metric its definition, unit, basis, direction, tier, inputs and where it
 * isn't meaningful. Every entry has an anchor (#roic) so other pages can link to it.
 */
export function MetricsDictionary() {
  const metrics = useMetrics();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<Category | "all">("all");

  const all = useMemo(() => metrics.data?.metrics ?? [], [metrics.data]);

  // #anchor links: entries render after the fetch (so the browser's own scroll finds nothing),
  // and a hash change while a tab or search hides the entry should still land on it.
  const [target, setTarget] = useState<string | null>(null);
  useEffect(() => {
    const onHash = () => {
      setQ("");
      setCat("all");
      setTarget(decodeURIComponent(window.location.hash.slice(1)) || null);
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (!target || all.length === 0) return;
    document.getElementById(target)?.scrollIntoView({ block: "start" });
  }, [target, all.length]);
  const names = useMemo(() => new Map(all.map((m) => [m.id, m.name])), [all]);
  const cats = useMemo(() => [...new Set(all.map((m) => m.category))], [all]);
  const needle = q.trim().toLowerCase();
  const shown = all.filter(
    (m) =>
      (cat === "all" || m.category === cat) &&
      (!needle || m.name.toLowerCase().includes(needle) || m.id.includes(needle) || m.definition.toLowerCase().includes(needle) || (m.tells_you ?? "").toLowerCase().includes(needle) || m.inputs.some((i) => i.includes(needle))),
  );

  return (
    <main className="mx-auto max-w-5xl space-y-4 px-4 py-6">
      <header className="space-y-1">
        <h1 className="text-title font-semibold">Metric dictionary</h1>
        <p className="text-label text-muted">
          Every metric Glint computes, with its formula, inputs, basis and unit.
        </p>
      </header>

      <StatusBanner error={metrics.error} />

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          aria-label="Search metrics"
          placeholder="Search by name, id, formula or input…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="h-ctl w-72 max-w-full rounded-control border border-line-strong bg-paper px-2.5 text-label focus:border-forest"
        />
        <p className="num text-meta text-muted" aria-live="polite">
          {formatCount(shown.length)} of {formatCount(all.length)}
        </p>
      </div>

      <div role="tablist" aria-label="Categories" className="flex flex-wrap gap-1 border-b border-line pb-2">
        {(["all", ...cats] as const).map((c) => (
          <button
            key={c}
            type="button"
            role="tab"
            aria-selected={cat === c}
            aria-controls="metric-list"
            onClick={() => setCat(c)}
            className={`h-7 rounded-control px-2.5 text-label ${cat === c ? "bg-dune text-ink-soft" : "text-muted hover:text-ink-soft"}`}
          >
            {c === "all" ? "All" : CATEGORY_LABEL[c]}
          </button>
        ))}
      </div>

      {metrics.isPending ? (
        <div className="space-y-2" role="status" aria-label="Loading metrics">
          {Array.from({ length: 6 }, (_, k) => (
            <div key={k} className="h-20 animate-pulse rounded-panel bg-dune" />
          ))}
        </div>
      ) : (
        <div id="metric-list" role="tabpanel" className="space-y-3">
          {shown.length === 0 && all.length > 0 && <p className="text-label text-ink-soft">No metric matches “{q}”. Try part of a name, such as “margin”, or clear the search.</p>}
          {shown.map((m) => (
            <MetricEntry key={m.id} m={m} names={names} targeted={m.id === target} />
          ))}
        </div>
      )}
    </main>
  );
}

const DIRECTION: Record<MetricDefinition["better"], { icon: "arrow-up" | "arrow-down" | null; text: string }> = {
  higher: { icon: "arrow-up", text: "Higher is better" },
  lower: { icon: "arrow-down", text: "Lower is better" },
  neutral: { icon: null, text: "Neither: context decides" },
};

/**
 * One entry (Phase 4.11): what it tells you first, then the formula in mono with the input and
 * null rules in the sans, when it misleads, the facts, and its inputs (metrics among them link to
 * their own entries). The heading is the entry's anchor; the link button copies it.
 */
function MetricEntry({ m, names, targeted }: { m: MetricDefinition; names: Map<string, string>; targeted: boolean }) {
  const notes = Object.entries(m.applicability?.notes ?? {});
  const nm = m.applicability?.not_meaningful ?? [];
  const { formula, rules } = splitDefinition(m.definition);
  const [copied, setCopied] = useState(false);
  const dir = DIRECTION[m.better];
  const copy = () => {
    void navigator.clipboard?.writeText(`${window.location.origin}${metricHref(m.id)}`).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <article id={m.id} aria-labelledby={`${m.id}-h`} className={`space-y-3 rounded-panel bg-paper p-panel ${targeted ? "shadow-[inset_2px_0_0_var(--purple)]" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id={`${m.id}-h`} className="text-section font-semibold text-ink">
            <a href={`#${m.id}`} className="rounded-control underline-offset-2 hover:underline">
              {m.name}
            </a>
          </h2>
          <p className="text-meta text-muted">
            {CATEGORY_LABEL[m.category]}, {m.tier === "price" ? "uses a market price" : "from SEC filings"}
          </p>
        </div>
        <button
          type="button"
          onClick={copy}
          aria-label={`Copy a link to ${m.name}`}
          className="inline-flex h-ctl shrink-0 items-center gap-1 rounded-control px-2 text-label text-muted hover:text-ink-soft"
        >
          <IconSwap name={copied ? "check" : "link"} names={["link", "check"]} />
          <span aria-live="polite">{copied ? "Copied" : "Link"}</span>
        </button>
      </div>

      {m.tells_you && <p className="max-w-prose text-prose text-ink-soft">{m.tells_you}</p>}

      <div className="space-y-1">
        <h3 className="text-label font-medium text-muted">Formula</h3>
        <Formula formula={formula} className="block rounded-panel bg-sand/60 px-3 py-2 text-cell break-words text-ink-soft" />
        {rules && <p className="max-w-prose text-label text-ink-soft">{rules}</p>}
      </div>

      {m.misleads && (
        <div className="max-w-prose border-l-2 border-caution pl-3">
          <h3 className="text-label font-medium text-muted">When it misleads</h3>
          <p className="text-label text-ink-soft">{m.misleads}</p>
        </div>
      )}

      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-label sm:grid-cols-[max-content_1fr_max-content_1fr]">
        <dt className="text-muted">Basis</dt>
        <dd className="text-ink-soft">{BASIS_LABEL[m.basis]}</dd>
        <dt className="text-muted">Unit</dt>
        <dd className="text-ink-soft">{UNIT_LABEL[m.unit]}</dd>
        <dt className="text-muted">Direction</dt>
        <dd className="inline-flex items-center gap-1 text-ink-soft">
          {dir.icon && <Icon name={dir.icon} />}
          {dir.text}
        </dd>
        <dt className="text-muted">Source</dt>
        <dd className="text-ink-soft">{TIER_LABEL[m.tier]}</dd>
      </dl>

      {m.inputs.length > 0 && (
        <p className="text-label text-ink-soft">
          <span className="text-muted">Inputs: </span>
          {m.inputs.map((i, k) => (
            <span key={i}>
              {k > 0 && ", "}
              {names.has(i) && i !== m.id ? (
                <a href={`#${i}`} className="text-forest underline underline-offset-2">
                  {names.get(i)}
                </a>
              ) : (
                <code className="font-code text-meta">{i}</code>
              )}
            </span>
          ))}
        </p>
      )}
      {(nm.length > 0 || notes.length > 0) && (
        <div className="space-y-1 rounded-panel bg-dune/60 px-3 py-2 text-label">
          {nm.length > 0 && (
            <p className="text-ink-soft">
              <span className="font-medium">Not meaningful (n/m) for </span>
              {nm.map((x) => SCOPE_LABEL[x]).join(", ")}.
            </p>
          )}
          {notes.map(([scope, text]) => (
            <p key={scope} className="text-ink-soft">
              <span className="font-medium">{SCOPE_LABEL[scope as keyof typeof SCOPE_LABEL] ?? scope}: </span>
              {plainText(text)}
            </p>
          ))}
        </div>
      )}
      <p className="text-meta text-muted">
        In screen files: <code className="font-code">{m.id}</code>
      </p>
    </article>
  );
}
