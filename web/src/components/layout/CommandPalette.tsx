"use client";

import { Icon } from "@/components/ui/Icon";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMetrics, usePresets, useSearch } from "@/lib/api/hooks";
import { sendCommand, type GlintCommand } from "@/lib/commands";
import { fuzzyFilter } from "@/lib/fuzzy";
import { applyPref, DENSITY_KEY } from "@/lib/prefs";
import { encodeScreen } from "@/lib/screen/codec";
import { MAX_PINNED, uiFromSearch } from "@/lib/screen/url";
import { emptyScreen } from "@/lib/screen/defaults";
import { metricMap } from "@/lib/screen/describe";
import { addFilter, newCondition } from "@/lib/screen/filters";
import { useDebounced } from "@/lib/useDebounced";

// The command palette (docs/ui-spec.md §4.10): "/" or ⌘K / Ctrl+K anywhere; tickers and
// company names first, then presets, filters and actions. Enter opens the drawer (on the
// screener) or the company page (elsewhere); ⌘/Ctrl+Enter always opens the full page.

type Item =
  | { kind: "company"; id: string; ticker: string; name: string; sector: string }
  | { kind: "preset"; id: string; name: string; summary: string }
  | { kind: "filter"; id: string; metric: string; name: string }
  | { kind: "action"; id: string; label: string; run: () => void };

const RECENT_KEY = "glint.recent";
const MAX = { company: 8, preset: 5, filter: 6 };

function readRecent(): { ticker: string; name: string; sector: string }[] {
  try {
    const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as unknown;
    return Array.isArray(v) ? (v as { ticker: string; name: string; sector: string }[]).slice(0, 5) : [];
  } catch {
    return [];
  }
}

function remember(c: { ticker: string; name: string; sector: string }) {
  try {
    const next = [c, ...readRecent().filter((r) => r.ticker !== c.ticker)].slice(0, 5);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Storage blocked: no recents, nothing else changes.
  }
}

/** A modal that is actually open: closed drawers keep their dialog in the DOM under aria-hidden. */
function openModal(): boolean {
  return [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')].some((d) => !d.closest('[aria-hidden="true"]'));
}

function typingIn(el: EventTarget | null): boolean {
  return el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));
}

/** Header trigger plus the palette dialog. One instance, in AppHeader. */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const cmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      const slash = e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey && !typingIn(e.target);
      if (!cmdK && !slash) return;
      if (!cmdK && openModal()) return;
      e.preventDefault();
      opener.current = document.activeElement as HTMLElement | null;
      setOpen(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const close = () => {
    setOpen(false);
    opener.current?.focus();
  };

  return (
    <>
      <button
        type="button"
        aria-keyshortcuts="/ Meta+K Control+K"
        onClick={(e) => {
          opener.current = e.currentTarget;
          setOpen(true);
        }}
        className="inline-flex h-8 min-w-0 items-center gap-3 rounded-control border border-sand-soft/60 px-3 text-label text-on-forest hover:border-on-forest sm:w-72"
      >
        <Icon name="search" />
        <span className="hidden truncate sm:inline">Search ticker or company</span>
        <span className="sr-only sm:hidden">Search</span>
        <kbd aria-hidden className="ml-auto hidden rounded-control border border-sand-soft/50 px-1.5 text-meta sm:inline">
          /
        </kbd>
      </button>
      {/* Portal: the header is a sticky stacking context, so the overlay must live on <body>. */}
      {open && createPortal(<PaletteDialog onClose={close} />, document.body)}
    </>
  );
}

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const path = usePathname();
  const onScreener = path === "/";
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const titleId = useId();

  const debounced = useDebounced(q, 120);
  const search = useSearch(debounced);
  const presets = usePresets();
  const metricsQ = useMetrics();
  const recent = useMemo(() => readRecent(), []);
  // Pins for comparison, as the screener's URL has them when the palette opened.
  const pinnedNow = useMemo(() => (onScreener ? (uiFromSearch(window.location.search).pinned ?? []) : []), [onScreener]);

  useEffect(() => input.current?.focus(), []);

  const run = (cmd: GlintCommand, fallback: () => void) => {
    if (onScreener) sendCommand(cmd);
    else fallback();
  };

  const groups = useMemo(() => {
    const needle = q.trim();
    const companies: Item[] = (needle
      ? (search.data?.query === debounced.trim() ? search.data.results : []).map((r) => ({ ticker: r.ticker, name: r.name, sector: r.sector as string }))
      : recent
    )
      .slice(0, MAX.company)
      .map((c) => ({ kind: "company", id: `c-${c.ticker}`, ...c }));
    const presetItems: Item[] = fuzzyFilter(needle, presets.data?.presets ?? [], (p) => `${p.name} ${p.summary}`)
      .slice(0, MAX.preset)
      .map((p) => ({ kind: "preset", id: `p-${p.id}`, name: p.name, summary: p.summary }));
    const filterItems: Item[] = needle
      ? fuzzyFilter(needle, metricsQ.data?.metrics ?? [], (m) => m.name)
          .slice(0, MAX.filter)
          .map((m) => ({ kind: "filter", id: `f-${m.id}`, metric: m.id, name: m.name }))
      : [];
    const actions: Item[] = fuzzyFilter(
      needle,
      [
        { kind: "action" as const, id: "a-compact", label: "Use compact rows", run: () => applyPref("density", "compact", DENSITY_KEY) },
        { kind: "action" as const, id: "a-comfortable", label: "Use comfortable rows", run: () => applyPref("density", "comfortable", DENSITY_KEY) },
        { kind: "action" as const, id: "a-shortcuts", label: "Show keyboard shortcuts", run: () => sendCommand({ kind: "show-shortcuts" }) },
        ...(onScreener
          ? [
              { kind: "action" as const, id: "a-share", label: "Copy a link to this screen", run: () => sendCommand({ kind: "share" }) },
              { kind: "action" as const, id: "a-export", label: "Download this screen as CSV", run: () => sendCommand({ kind: "export" }) },
              // Pin the top company match; compare once two are pinned.
              ...(needle ? companies.slice(0, 1) : []).flatMap((c) =>
                c.kind === "company"
                  ? [
                      {
                        kind: "action" as const,
                        id: `a-pin-${c.ticker}`,
                        label: pinnedNow.includes(c.ticker.toUpperCase())
                          ? `Unpin ${c.ticker} from comparison`
                          : `Pin ${c.ticker} for comparison${pinnedNow.length >= MAX_PINNED ? ` (drops ${pinnedNow[0]})` : ""}`,
                        run: () => sendCommand({ kind: "pin-company", ticker: c.ticker }),
                      },
                    ]
                  : [],
              ),
              ...(pinnedNow.length >= 2
                ? [{ kind: "action" as const, id: "a-compare", label: `Compare pinned companies (${pinnedNow.join(", ")})`, run: () => sendCommand({ kind: "compare" }) }]
                : []),
            ]
          : []),
      ],
      (a) => a.label,
    );
    return [
      { label: needle ? "Companies" : "Recent companies", items: companies },
      { label: "Presets", items: presetItems },
      { label: "Add a filter", items: filterItems },
      { label: "Actions", items: actions },
    ].filter((g) => g.items.length > 0);
  }, [q, debounced, search.data, recent, presets.data, metricsQ.data, onScreener, pinnedNow]);

  const flat = groups.flatMap((g) => g.items);
  const current = flat[Math.min(active, flat.length - 1)];
  const optionId = (it: Item) => `${listId}-${it.id}`;

  const choose = (it: Item, fullPage: boolean) => {
    onClose();
    switch (it.kind) {
      case "company": {
        remember({ ticker: it.ticker, name: it.name, sector: it.sector });
        if (fullPage || !onScreener) router.push(`/company/${encodeURIComponent(it.ticker)}`);
        else sendCommand({ kind: "open-company", ticker: it.ticker });
        return;
      }
      case "preset":
        return run({ kind: "apply-preset", id: it.id.slice(2) }, () => router.push(`/?preset=${encodeURIComponent(it.id.slice(2))}`));
      case "filter":
        return run({ kind: "add-filter", metric: it.metric }, () => {
          const metrics = metricMap(metricsQ.data?.metrics ?? []);
          router.push(`/?s=${encodeScreen(addFilter(emptyScreen(), newCondition(it.metric, metrics)))}`);
        });
      case "action":
        return it.run();
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = flat.length || 1;
      setActive((a) => (a + (e.key === "ArrowDown" ? 1 : -1) + n) % n);
    } else if (e.key === "Enter" && current) {
      e.preventDefault();
      choose(current, e.metaKey || e.ctrlKey);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "Tab") {
      e.preventDefault(); // one focusable control: the input
    }
  };

  useEffect(() => {
    if (current) document.getElementById(optionId(current))?.scrollIntoView({ block: "nearest" });
  });

  const searching = q.trim() !== "" && (search.isFetching || debounced.trim() !== q.trim());
  const searchFailed = q.trim() !== "" && search.isError;

  return (
    <div className="fixed inset-x-0 top-banner bottom-0 z-50 flex items-start justify-center bg-ink/20 sm:p-4 sm:pt-[15dvh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col bg-paper shadow-overlay sm:h-auto sm:max-h-[70dvh] sm:max-w-[35rem] sm:rounded-sheet"
      >
        <h2 id={titleId} className="sr-only">
          Search and commands
        </h2>
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Icon name="search" />
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={current ? optionId(current) : undefined}
            aria-autocomplete="list"
            aria-label="Search ticker or company, or type a command"
            placeholder="Search ticker or company, or type a command"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            className="h-12 min-w-0 flex-1 bg-transparent text-section text-ink outline-none placeholder:text-muted focus-visible:shadow-none"
          />
          <button type="button" onClick={onClose} className="text-label text-muted hover:text-ink sm:hidden">
            Close
          </button>
        </div>
        <div id={listId} role="listbox" aria-label="Results" className="min-h-0 flex-1 overflow-y-auto p-2">
          {groups.map((g) => (
            <div key={g.label} role="group" aria-label={g.label} className="pb-2">
              <p className="px-2 pt-1 pb-1 text-meta font-medium text-muted" aria-hidden>
                {g.label}
              </p>
              {g.items.map((it) => {
                const isActive = it === current;
                return (
                  <div
                    key={it.id}
                    id={optionId(it)}
                    role="option"
                    aria-selected={isActive}
                    onMouseMove={() => setActive(flat.indexOf(it))}
                    onClick={(e) => choose(it, e.metaKey || e.ctrlKey)}
                    className={`flex min-h-10 cursor-pointer items-baseline gap-3 rounded-in-sheet px-2 py-1.5 ${
                      isActive ? "bg-purple/10 shadow-[inset_3px_0_0_var(--purple)]" : ""
                    }`}
                  >
                    <ItemView it={it} active={isActive} />
                  </div>
                );
              })}
            </div>
          ))}
          {searching && <p className="px-2 py-1 text-label text-muted">Searching companies…</p>}
          {searchFailed && <p className="px-2 py-1 text-label text-ink-soft">Company search isn&apos;t available right now. Commands still work.</p>}
          {!searching && !searchFailed && flat.length === 0 && (
            <p className="px-2 py-3 text-prose text-ink-soft">No company or command matches &ldquo;{q.trim()}&rdquo;. Try a ticker or part of a company name.</p>
          )}
        </div>
        <p className="hidden border-t border-line px-4 py-2 text-meta text-muted sm:block">
          ↑ ↓ to move. Enter to open{onScreener ? " in the drawer" : ""}. ⌘ Enter for the full company page. Esc to close.
        </p>
      </div>
    </div>
  );
}

function ItemView({ it, active }: { it: Item; active: boolean }) {
  const main = active ? "text-purple-ink" : "text-ink-soft";
  switch (it.kind) {
    case "company":
      return (
        <>
          <span className="num w-16 shrink-0 text-label font-semibold text-forest">{it.ticker}</span>
          <span className={`min-w-0 flex-1 truncate text-label ${main}`}>{it.name}</span>
          <span className="hidden shrink-0 text-meta text-muted sm:inline">{it.sector}</span>
        </>
      );
    case "preset":
      return (
        <>
          <span className={`text-label ${main}`}>Apply preset: {it.name}</span>
          <span className="hidden min-w-0 flex-1 truncate text-meta text-muted sm:inline">{it.summary}</span>
        </>
      );
    case "filter":
      return <span className={`text-label ${main}`}>Add filter: {it.name}</span>;
    case "action":
      return <span className={`text-label ${main}`}>{it.label}</span>;
  }
}
