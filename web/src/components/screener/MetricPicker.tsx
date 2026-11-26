"use client";

import { Formula } from "@/components/ui/Formula";
import { metricHref, splitDefinition } from "@/lib/metricText";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { components } from "@/lib/api/types";
import { FILTER_FIELDS } from "@/lib/screen/filters";
import { BASIS_LABEL, BETTER_LABEL, CATEGORY_LABEL, CATEGORY_ORDER, TIER_LABEL, UNIT_LABEL } from "@/lib/labels";
import type { MetricDefinition } from "@/lib/screen/types";

type Category = components["schemas"]["Category"];


type Option = { id: string; name: string; group: Category | "classification"; def: MetricDefinition | null };

type PickerProps = {
  metrics: MetricDefinition[];
  onPick: (id: string) => void;
  onClose: () => void;
  title?: string;
};

/** Searchable metric picker (SPEC WT-05 step 5): category groups, definition and unit preview. */
export function MetricPicker({ open, ...props }: PickerProps & { open: boolean }) {
  // Mounted only while open, so every opening starts with an empty search.
  return open ? <PickerBody {...props} /> : null;
}

function PickerBody({ metrics, onPick, onClose, title = "Add a filter" }: PickerProps) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const titleId = useId();

  const options = useMemo<Option[]>(() => {
    const all: Option[] = [
      ...metrics.map((m) => ({ id: m.id, name: m.name, group: m.category, def: m })),
      ...Object.entries(FILTER_FIELDS).map(([id, f]) => ({ id, name: f.name, group: "classification" as const, def: null })),
    ];
    const needle = q.trim().toLowerCase();
    const order: string[] = CATEGORY_ORDER;
    return all
      .filter((o) => !needle || o.name.toLowerCase().includes(needle) || o.id.includes(needle) || (o.def?.definition.toLowerCase().includes(needle) ?? false))
      .sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
  }, [metrics, q]);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    input.current?.focus();
    return () => opener?.focus();
  }, []);

  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);

  const current = options[Math.min(active, options.length - 1)];

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, options.length - 1));
    else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
    else if (e.key === "Enter" && current) onPick(current.id);
    else if (e.key === "Escape") onClose();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <div className="fixed inset-x-0 top-banner bottom-0 z-40 flex items-start justify-center bg-ink/20 p-4 pt-[12dvh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(e) => e.stopPropagation()}
        className="flex max-h-[70dvh] w-full max-w-3xl flex-col overflow-hidden rounded-sheet border border-line-strong bg-paper shadow-overlay"
      >
        <div className="border-b border-line p-panel">
          <h2 id={titleId} className="mb-2 text-section font-semibold text-ink-soft">
            {title}
          </h2>
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={current ? `${listId}-${options.indexOf(current)}` : undefined}
            aria-label="Search metrics"
            placeholder="Search metrics: ROIC, margin, debt…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKey}
            className="h-ctl w-full rounded-control border border-line-strong bg-paper px-2.5 text-label focus:border-forest"
          />
        </div>
        <div className="grid min-h-0 flex-1 md:grid-cols-[minmax(0,1fr)_18rem]">
          <ul id={listId} role="listbox" aria-label="Metrics" className="min-h-0 overflow-y-auto p-1">
            {options.length === 0 && <li className="p-3 text-label text-ink-soft">No metric matches “{q}”. Try part of a name, such as “margin” or “yield”.</li>}
            {options.map((o, i) => {
              const header = i === 0 || options[i - 1]?.group !== o.group ? CATEGORY_LABEL[o.group] : null;
              return (
                <li key={o.id} role="presentation">
                  {header && (
                    <div role="presentation" className="px-2 pt-2 pb-1 text-meta font-medium text-muted">
                      {header}
                    </div>
                  )}
                  <div
                    id={`${listId}-${i}`}
                    role="option"
                    aria-label={o.name}
                    aria-selected={i === active}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => onPick(o.id)}
                    className="flex cursor-pointer items-center justify-between gap-2 rounded-control px-2 py-1.5 text-label aria-selected:bg-dune"
                  >
                    <span>{o.name}</span>
                    <span className="font-code text-meta text-muted">{o.id}</span>
                  </div>
                </li>
              );
            })}
          </ul>
          <aside aria-live="polite" className="hidden border-l border-line p-panel text-label md:block">
            {current && <Preview option={current} />}
          </aside>
        </div>
      </div>
    </div>
  );
}

function Preview({ option }: { option: Option }) {
  const d = option.def;
  if (!d) return <p className="text-muted">Filter companies by their Glint sector (from the SIC code).</p>;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <p className="font-medium">{d.name}</p>
      </div>
      {d.tells_you && <p className="text-ink-soft">{d.tells_you}</p>}
      <Formula formula={splitDefinition(d.definition).formula} className="block text-meta text-ink-soft" />
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-meta">
        <dt className="text-muted">Unit</dt>
        <dd>{UNIT_LABEL[d.unit]}</dd>
        <dt className="text-muted">Basis</dt>
        <dd>{BASIS_LABEL[d.basis]}</dd>
        <dt className="text-muted">Direction</dt>
        <dd>{BETTER_LABEL[d.better]}</dd>
        <dt className="text-muted">Source</dt>
        <dd>{TIER_LABEL[d.tier]}</dd>
      </dl>
      <a href={metricHref(d.id)} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-label text-forest underline underline-offset-2">
        Full entry in the metric dictionary
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
      {d.inputs.length > 0 && <p className="text-meta break-words text-muted">Inputs: <span className="font-code">{d.inputs.join(", ")}</span></p>}
    </div>
  );
}
