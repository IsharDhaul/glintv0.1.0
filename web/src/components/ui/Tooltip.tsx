import { Icon } from "@/components/ui/Icon";
import { useId, type ReactNode } from "react";

/**
 * Hover- and keyboard-reachable tooltip (SPEC §3.5). The trigger is focusable and points at the
 * tip with aria-describedby, so screen readers announce it on focus. When the trigger is itself a
 * link or button, pass children as a function: it gets the aria-describedby to put on that
 * control, and the wrapper adds no tab stop of its own.
 */
export function Tooltip({
  tip,
  children,
  side = "top",
  className = "",
}: {
  tip: ReactNode;
  children: ReactNode | ((describedBy: { "aria-describedby": string }) => ReactNode);
  side?: "top" | "bottom";
  /** On the wrapper, e.g. `min-w-0` so a truncating trigger can shrink inside a grid cell. */
  className?: string;
}) {
  const id = useId();
  return (
    <span className={`group relative inline-flex ${className}`}>
      {typeof children === "function" ? (
        children({ "aria-describedby": id })
      ) : (
        <span tabIndex={0} aria-describedby={id} className="cursor-help rounded-control">
          {children}
        </span>
      )}
      <span
        role="tooltip"
        id={id}
        className={`pointer-events-none absolute left-1/2 z-40 hidden w-max max-w-[min(18rem,80vw)] -translate-x-1/2 rounded-panel border border-line bg-paper px-3 py-2 text-left text-meta font-normal whitespace-normal text-ink-soft shadow-overlay group-focus-within:block group-hover:block ${
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5"
        }`}
      >
        {tip}
      </span>
    </span>
  );
}

/**
 * An info button beside a heading: the explanation lives here, not in a subtitle under every
 * section (Visual standard). `label` names it for screen readers ("About the sieve").
 */
export function InfoTip({ label, children, side = "bottom" }: { label: string; children: ReactNode; side?: "top" | "bottom" }) {
  return (
    <Tooltip tip={children} side={side}>
      <span role="img" aria-label={label} className="inline-flex size-5 items-center justify-center text-meta text-muted hover:text-ink-soft">
        <Icon name="info" />
      </span>
    </Tooltip>
  );
}
