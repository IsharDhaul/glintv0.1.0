"use client";

import { useEffect, useId, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { Tooltip } from "@/components/ui/Tooltip";
import { useMeta } from "@/lib/api/hooks";
import type { components } from "@/lib/api/types";
import { formatCount } from "@/lib/format";
import { universeChips } from "@/lib/screen/universe";
import type { Screen } from "@/lib/screen/types";

type Universe = components["schemas"]["Universe"];

/**
 * The universe behind one control (Phase 4.13): a button with the rule count, the excluded count
 * always beside it (principle 6), and a panel listing each rule in plain words. Removable rules
 * have a remove button; locked ones a lock and the reason. Esc or a click outside closes it.
 */
export function UniverseControl({
  universe,
  onUniverse,
  excluded,
  buildCount,
  open,
  onOpenChange,
}: {
  universe: Screen["universe"];
  onUniverse: (patch: Partial<Universe>) => void;
  excluded: number | null;
  buildCount: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const meta = useMeta();
  const rules = universeChips(universe, meta.data?.universe_rules);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const onOpenChangeRef = useRef(onOpenChange);
  useEffect(() => {
    onOpenChangeRef.current = onOpenChange;
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) onOpenChangeRef.current(false);
    };
    const onKey = (e: KeyboardEvent) => {
      const focusHere = root.current?.contains(document.activeElement) || document.activeElement === document.body;
      if (e.key !== "Escape" || !focusHere) return;
      e.preventDefault();
      onOpenChangeRef.current(false);
      button.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const outside = excluded === null ? null : `${formatCount(excluded)}${buildCount !== null ? ` of ${formatCount(buildCount)}` : ""} companies in this build are outside the universe. The screen never covers them.`;

  return (
    <div ref={root} className="relative flex items-center gap-2">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onOpenChange(!open)}
        className="inline-flex h-ctl items-center gap-1.5 rounded-control border border-line-strong bg-paper px-2.5 text-label text-ink-soft hover:border-ink-soft active:bg-dune"
      >
        Universe
        <span className="num text-muted">{formatCount(rules.length)} rules</span>
        <Icon name="chevron-down" className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>
      {excluded !== null && outside && (
        <Tooltip side="bottom" tip={outside}>
          <span className="num text-label text-caution">{formatCount(excluded)} excluded</span>
        </Tooltip>
      )}
      {open && (
        <div id={panelId} className="in-sheet absolute top-full left-0 z-30 mt-1 w-[min(24rem,calc(100vw-2rem))] rounded-sheet bg-paper p-2 shadow-overlay">
          <ul ref={list} id="universe-chips" tabIndex={-1} aria-label="Universe" className="divide-y divide-line rounded-in-sheet focus:outline-none">
            {rules.map((c) => (
              <li key={`${c.key}-${c.label}`} className="flex items-start gap-2 px-2 py-1.5">
                <div className="min-w-0 flex-1">
                  <p className="text-label text-ink-soft">{c.label}</p>
                  {c.hint && c.hint !== `${c.label}.` && <p className="text-meta text-muted">{c.hint}</p>}
                </div>
                {c.clear ? (
                  <button
                    type="button"
                    onClick={() => {
                      onUniverse(c.clear as Partial<Universe>);
                      // The button goes with its rule: keep focus in the panel.
                      list.current?.focus();
                    }}
                    aria-label={`Remove universe rule: ${c.label}`}
                    className="inline-flex size-ctl shrink-0 items-center justify-center rounded-control text-muted hover:bg-dune hover:text-ink"
                  >
                    <Icon name="close" />
                  </button>
                ) : (
                  <Tooltip side="bottom" tip={c.lockReason ?? "Glint always applies this rule."}>
                    <span role="img" aria-label={`Locked: ${c.lockReason ?? "Glint always applies this rule."}`} className="inline-flex size-ctl shrink-0 items-center justify-center text-muted">
                      <Icon name="lock" />
                    </span>
                  </Tooltip>
                )}
              </li>
            ))}
          </ul>
          {outside && <p className="mt-1 border-t border-line px-2 pt-2 text-meta text-muted">{outside}</p>}
        </div>
      )}
    </div>
  );
}
