"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { onCommand } from "@/lib/commands";

// The keyboard map (docs/ui-spec.md §6.3). Shown with "?" or from Settings.
const SHORTCUTS: [string[], string][] = [
  [["/", "⌘ K"], "Search companies, presets, filters and actions"],
  [["f"], "Add a filter"],
  [["j", "k"], "Next / previous result (also in the drawer)"],
  [["↑", "↓"], "Next / previous result when a row has focus"],
  [["Home", "End"], "First / last result"],
  [["Enter"], "Open the drawer for the focused row"],
  [["o"], "Open the full company page for the focused row"],
  [["x"], "Pin or unpin the focused row or open company for comparison (up to 3)"],
  [["c"], "Compare the pinned companies"],
  [["Esc"], "Close the drawer, palette, picker, menu or sheet"],
  [["?"], "Show this list"],
];

function typingIn(el: EventTarget | null): boolean {
  return el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));
}

/** Keyboard shortcuts dialog: "?" anywhere (not while typing), or Settings → Keyboard shortcuts. */
export function ShortcutsHelp() {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "?" && !typingIn(e.target) && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        opener.current = document.activeElement as HTMLElement | null;
        setOpen(true);
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    const off = onCommand((c) => {
      if (c.kind !== "show-shortcuts") return;
      opener.current = document.activeElement as HTMLElement | null;
      setOpen(true);
    });
    return () => {
      document.removeEventListener("keydown", onKey);
      off();
    };
  }, [open]);

  useEffect(() => {
    if (open) closeRef.current?.focus();
    else opener.current?.focus();
  }, [open]);

  return (
    <>
      {open &&
        createPortal(
        <div className="fixed inset-x-0 top-banner bottom-0 z-50 flex items-start justify-center bg-ink/30 p-4 pt-[15dvh]" onMouseDown={() => setOpen(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onMouseDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              // One focusable element: keep Tab inside the dialog.
              if (e.key === "Tab") {
                e.preventDefault();
                closeRef.current?.focus();
              }
            }}
            className="w-full max-w-md rounded-sheet bg-paper p-panel shadow-overlay"
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 id={titleId} className="text-label font-semibold">
                Keyboard shortcuts
              </h2>
              <button ref={closeRef} type="button" onClick={() => setOpen(false)} className="rounded-control px-2 py-0.5 text-label text-muted hover:text-ink-soft">
                Close <span className="text-meta">(Esc)</span>
              </button>
            </div>
            <dl className="space-y-1.5 text-label">
              {SHORTCUTS.map(([keys, what]) => (
                <div key={what} className="flex items-center justify-between gap-4">
                  <dt className="flex gap-1">
                    {keys.map((k) => (
                      <kbd key={k} className="min-w-6 rounded-control border border-line-strong bg-paper px-1.5 text-center font-code text-meta">
                        {k}
                      </kbd>
                    ))}
                  </dt>
                  <dd className="text-right text-muted">{what}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-meta text-muted">Shortcuts are off while you type in a field.</p>
          </div>
        </div>,
          document.body,
        )}
    </>
  );
}
