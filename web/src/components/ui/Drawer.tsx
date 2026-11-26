"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { IconButton } from "./Button";

function typingIn(el: EventTarget | null): boolean {
  return el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));
}

/**
 * Right-hand drawer (company quick view, docs/ui-spec.md §4.5). 480px on desktop, full width on
 * small screens; on large screens it doesn't dim the page, so the table's ticker column stays
 * readable beside it. Esc and the backdrop close it; focus moves in on open, stays inside, and
 * returns to the opener on close. With `onStep`, j/k (or ↑/↓) move to the next or previous item
 * without closing.
 */
export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  header,
  actions,
  footer,
  onStep,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Extra header content under the title (figures, the screen check). */
  header?: ReactNode;
  /** Buttons beside the close button. */
  actions?: ReactNode;
  /** A strip pinned to the bottom (position, previous/next). */
  footer?: ReactNode;
  onStep?: (dir: 1 | -1) => void;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // Handlers are read through refs so a parent re-render (often a new arrow) never re-runs the
  // effect below, which would bounce focus to the opener and back (review fix).
  const onCloseRef = useRef(onClose);
  const onStepRef = useRef(onStep);
  useEffect(() => {
    onCloseRef.current = onClose;
    onStepRef.current = onStep;
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
      } else if (onStepRef.current && !typingIn(e.target) && !e.metaKey && !e.ctrlKey && !e.altKey && ["j", "k", "ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        onStepRef.current(e.key === "j" || e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "Tab" && panel.current) {
        const focusables = panel.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input, select, textarea, summary, [tabindex]:not([tabindex="-1"])',
        );
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
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

  return (
    <div className={`fixed inset-x-0 top-banner bottom-0 z-30 ${open ? "" : "pointer-events-none"}`} aria-hidden={!open}>
      <div
        onClick={onClose}
        className={`absolute inset-0 bg-ink/20 transition-opacity duration-200 ease-out lg:bg-transparent ${open ? "opacity-100" : "opacity-0"}`}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        inert={!open}
        className={`absolute top-0 right-0 bottom-0 flex w-full flex-col bg-paper shadow-overlay transition-transform duration-[160ms] ease-out focus:outline-none sm:max-w-[30rem] sm:rounded-l-sheet ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="space-y-2 border-b border-line p-panel">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 id={titleId} className="truncate text-section font-semibold text-ink">
                {title}
              </h2>
              {subtitle && <div className="mt-0.5 text-label text-ink-soft">{subtitle}</div>}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {actions}
              <IconButton label="Close (Esc)" onClick={onClose}>
                <Icon name="close" />
              </IconButton>
            </div>
          </div>
          {header}
        </header>
        <div className="in-sheet flex-1 overflow-y-auto p-panel">{children}</div>
        {footer && <footer className="border-t border-line px-panel py-2">{footer}</footer>}
      </div>
    </div>
  );
}
