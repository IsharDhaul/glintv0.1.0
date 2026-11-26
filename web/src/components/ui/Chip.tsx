import { Icon } from "@/components/ui/Icon";
import type { ReactNode } from "react";

/**
 * A chip is only for something the user can remove or toggle (docs/ui-spec.md §4.9): a universe
 * rule, a near-miss filter toggle, a pinned ticker. Anything non-interactive is plain text.
 * - `onToggle` + `pressed`: a toggle button (forest when pressed).
 * - `onRemove`: a close button; `locked` shows a lock instead, with `lockReason` as its tooltip.
 */
export function Chip({
  children,
  pressed,
  onToggle,
  onRemove,
  removeLabel,
  locked = false,
  lockReason,
}: {
  children: ReactNode;
  pressed?: boolean;
  onToggle?: () => void;
  onRemove?: () => void;
  removeLabel?: string;
  locked?: boolean;
  lockReason?: string;
}) {
  const base = "inline-flex h-6 max-w-72 items-center gap-1 rounded-full border px-2.5 text-label whitespace-nowrap";
  if (onToggle) {
    return (
      <button
        type="button"
        aria-pressed={pressed ?? false}
        onClick={onToggle}
        className={`${base} truncate transition-colors duration-150 ease-out ${
          pressed ? "border-forest bg-forest text-on-forest" : "border-line-strong bg-paper text-ink-soft hover:border-ink-soft active:bg-dune"
        }`}
      >
        {children}
      </button>
    );
  }
  return (
    <span className={`${base} ${locked ? "border-line bg-paper text-muted" : "border-line-strong bg-paper text-ink-soft"}`}>
      {children}
      {locked ? (
        <span title={lockReason} aria-label={lockReason ? `Locked: ${lockReason}` : "Locked"} role="img" className="-mr-0.5 inline-flex size-4 items-center justify-center">
          <Icon name="lock" />
        </span>
      ) : (
        onRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={removeLabel ?? "Remove"}
            className="-mr-1 inline-flex size-4 items-center justify-center rounded-full text-muted hover:text-ink"
          >
            <Icon name="close" />
          </button>
        )
      )}
    </span>
  );
}
