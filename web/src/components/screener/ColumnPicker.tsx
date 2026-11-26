"use client";

import { Icon } from "@/components/ui/Icon";
import { useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "@/components/ui/Button";
import { BADGE_COLUMNS } from "@/lib/screen/columns";
import type { MetricDefinition } from "@/lib/screen/types";
import { columnDef } from "./columns";
import { CATEGORY_LABEL } from "@/lib/labels";

const FIELDS = ["name", "sector", "exchange"];

/**
 * Column picker: the chosen columns in order (move up/down, remove), then every other metric by
 * category with a search. Ticker is always first and the badge columns are always on.
 */
export function ColumnPicker({
  columns,
  metrics,
  ranked,
  onChange,
}: {
  /** Chosen columns without ticker. */
  columns: string[];
  metrics: Map<string, MetricDefinition>;
  ranked: boolean;
  onChange: (columns: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const available = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const ids = [...FIELDS, ...(ranked ? ["rank_score"] : []), ...[...metrics.keys()].filter((id) => !(BADGE_COLUMNS as readonly string[]).includes(id))];
    return ids
      .filter((id) => !columns.includes(id))
      .filter((id) => !needle || columnDef(id, metrics).label.toLowerCase().includes(needle) || id.includes(needle));
  }, [q, columns, metrics, ranked]);

  const move = (i: number, d: -1 | 1) => {
    const next = columns.slice();
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j] as string, next[i] as string];
    onChange(next);
  };

  const groupOf = (id: string) => metrics.get(id)?.category ?? "classification";

  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-ctl items-center gap-1.5 rounded-control border border-line-strong bg-paper px-3 text-label hover:border-forest"
      >
        Columns <Icon name="chevron-down" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Choose columns"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setOpen(false);
              button.current?.focus();
            }
          }}
          className="absolute top-full right-0 z-30 mt-1 flex max-h-[60dvh] w-80 flex-col rounded-sheet bg-paper shadow-overlay"
        >
          <div className="border-b border-line p-2">
            <p className="mb-1 text-meta font-medium text-muted">Shown, in order</p>
            <ol className="space-y-0.5">
              <li className="flex h-7 items-center px-1 text-label text-muted">Ticker (pinned)</li>
              {columns.map((id, i) => (
                <li key={id} className="flex h-7 items-center gap-1 rounded-in-sheet px-1 text-label hover:bg-dune/50">
                  <span className="flex-1 truncate">{columnDef(id, metrics).label}</span>
                  <IconButton label={`Move ${columnDef(id, metrics).label} left`} onClick={() => move(i, -1)} disabled={i === 0} className="size-6">
                    <Icon name="arrow-up" />
                  </IconButton>
                  <IconButton label={`Move ${columnDef(id, metrics).label} right`} onClick={() => move(i, 1)} disabled={i === columns.length - 1} className="size-6">
                    <Icon name="arrow-down" />
                  </IconButton>
                  <IconButton label={`Hide ${columnDef(id, metrics).label}`} onClick={() => onChange(columns.filter((c) => c !== id))} className="size-6">
                    <Icon name="close" />
                  </IconButton>
                </li>
              ))}
            </ol>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <input
              ref={search}
              aria-label="Search columns"
              placeholder="Add a column…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="mb-1 h-ctl w-full rounded-in-sheet border border-line-strong bg-paper px-2 text-label focus:border-forest"
            />
            <ul aria-label="Available columns">
              {available.map((id, i) => {
                const header = i === 0 || groupOf(available[i - 1] as string) !== groupOf(id);
                return (
                  <li key={id}>
                    {header && <p className="px-1 pt-2 text-meta font-medium text-muted">{CATEGORY_LABEL[groupOf(id)]}</p>}
                    <button
                      type="button"
                      onClick={() => onChange([...columns, id])}
                      className="flex h-7 w-full items-center justify-between rounded-control px-1 text-left text-label hover:bg-paper"
                    >
                      <span>{columnDef(id, metrics).label}</span>
                      <span aria-hidden className="text-muted">
                        +
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
