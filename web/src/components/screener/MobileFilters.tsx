"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { formatCount } from "@/lib/format";

/**
 * Below 1024px the filter rail becomes this sticky bar (docs/ui-spec.md §2): the screen in one
 * line ("5 filters, 139 results") and a Filters button that opens the sheet. On phones a one-line
 * sieve summary sits under it.
 */
export function FiltersBar({ filters, results, onOpen, summary }: { filters: number; results: number | null; onOpen: () => void; summary?: ReactNode }) {
  return (
    <div className="sticky top-[calc(var(--banner-h)+var(--header-h))] z-10 -mx-4 border-b border-line bg-sand/95 px-4 py-2 backdrop-blur-sm">
      <div className="flex items-center gap-2">
        <p className="num text-label text-ink-soft" aria-live="polite">
          {formatCount(filters)} {filters === 1 ? "filter" : "filters"}
          {results !== null && (
            <>
              , <span className="font-semibold text-ink">{formatCount(results)}</span> {results === 1 ? "result" : "results"}
            </>
          )}
        </p>
        <Button variant="primary" onClick={onOpen} className="ml-auto" aria-haspopup="dialog">
          Filters{filters > 0 ? ` (${formatCount(filters)})` : ""}
        </Button>
      </div>
      {summary && <p className="mt-1 text-meta text-muted">{summary}</p>}
    </div>
  );
}

/**
 * The filters sheet: from the bottom on phones (90% of the screen), from the left on tablets.
 * Modal: Esc closes it (unless a dialog opened from inside it is on top), focus returns to the
 * opener. The footer button closes it and says how many companies the screen keeps.
 */
export function FiltersSheet({
  open,
  onClose,
  side,
  results,
  children,
}: {
  open: boolean;
  onClose: () => void;
  side: "bottom" | "left";
  results: number | null;
  children: ReactNode;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      // Only when this sheet is the top dialog: the metric picker opens over it.
      const dialogs = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]:not([inert])')];
      if (dialogs.at(-1) !== panel.current) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
      } else if (e.key === "Tab" && panel.current) {
        const f = panel.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, textarea, summary, [tabindex]:not([tabindex="-1"])');
        const first = f[0];
        const last = f[f.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
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

  if (!open) return null;
  const placement =
    side === "bottom"
      ? "inset-x-0 bottom-0 h-[90dvh] rounded-t-sheet"
      : "top-banner bottom-0 left-0 w-[24rem] max-w-[90vw] rounded-r-sheet";
  return createPortal(
    <div className="fixed inset-x-0 top-banner bottom-0 z-30 bg-ink/30" onMouseDown={onClose}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
        className={`fixed flex flex-col bg-sand shadow-overlay focus:outline-none ${placement}`}
      >
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2">
          <h2 id={titleId} className="text-section font-semibold text-ink">
            Edit the screen
          </h2>
          <button type="button" onClick={onClose} aria-label="Close filters (Esc)" className="inline-flex size-ctl items-center justify-center rounded-control text-muted hover:text-ink">
            <Icon name="close" />
          </button>
        </header>
        <div className="flex-1 space-y-4 overflow-y-auto overscroll-contain p-4">{children}</div>
        <footer className="border-t border-line px-4 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
          <Button variant="primary" onClick={onClose} className="w-full justify-center">
            {results === null ? "Show results" : `Show ${formatCount(results)} ${results === 1 ? "result" : "results"}`}
          </Button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
