"use client";

import { Icon } from "@/components/ui/Icon";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export type MenuItem = { id: string; label: ReactNode; hint?: ReactNode; checked?: boolean; onSelect: () => void };

/**
 * Menu button (WAI-ARIA menu pattern): Enter/Space/↓ opens and focuses the first item,
 * ↑/↓/Home/End move, Esc closes and returns focus, clicking outside closes.
 */
export function Menu({
  label,
  items,
  align = "end",
  variant = "default",
}: {
  label: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
  /** "band": the trigger sits on the forest header band. */
  variant?: "default" | "band";
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    itemRefs.current[0]?.focus();
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };

  const onMenuKey = (e: React.KeyboardEvent) => {
    const els = itemRefs.current.filter((x): x is HTMLButtonElement => x !== null);
    const i = els.indexOf(document.activeElement as HTMLButtonElement);
    const go = (j: number) => els[(j + els.length) % els.length]?.focus();
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(els.length - 1);
    else if (e.key === "Escape") close();
    else if (e.key === "Tab") setOpen(false);
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className={
          variant === "band"
            ? "inline-flex h-8 items-center gap-1.5 rounded-control px-2 text-label text-sand-soft transition-colors duration-150 ease-out hover:text-on-forest"
            : "inline-flex h-ctl items-center gap-1.5 rounded-control border border-line-strong bg-paper px-3 text-label text-ink-soft transition-colors duration-150 ease-out hover:border-ink-soft"
        }
      >
        {label} <Icon name="chevron-down" />
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          onKeyDown={onMenuKey}
          className={`absolute top-full z-40 mt-1 w-72 rounded-sheet bg-paper p-2 shadow-overlay ${align === "end" ? "right-0" : "left-0"}`}
        >
          {items.map((item, i) => (
            <button
              key={item.id}
              ref={(el) => {
                itemRefs.current[i] = el;
              }}
              type="button"
              role={item.checked === undefined ? "menuitem" : "menuitemradio"}
              aria-checked={item.checked}
              tabIndex={-1}
              onClick={() => {
                item.onSelect();
                close();
              }}
              className="flex w-full items-start gap-2 rounded-in-sheet px-2.5 py-1.5 text-left text-label text-ink-soft hover:bg-dune/50 focus:bg-dune/50"
            >
              {item.checked !== undefined && (
                <span aria-hidden className="w-3 shrink-0 text-forest">
                  {item.checked ? <Icon name="check" /> : null}
                </span>
              )}
              <span className="min-w-0">
                <span className="block">{item.label}</span>
                {item.hint && <span className="block text-meta text-muted">{item.hint}</span>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
