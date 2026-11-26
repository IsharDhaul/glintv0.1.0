"use client";

import { Icon, type IconName } from "./Icon";

/**
 * Two icons in one slot, crossfading when `name` changes (Visual standard, craft rules): the
 * outgoing icon blurs (4px) and shrinks slightly as it fades, the incoming one sharpens in.
 * Every icon in `names` stays mounted, so the swap is a pure CSS transition; reduced motion
 * (globals.css) makes it instant.
 */
export function IconSwap({ name, names, weight = 400, className = "" }: { name: IconName | null; names: IconName[]; weight?: 400 | 500 | 600; className?: string }) {
  return (
    <span aria-hidden className={`relative inline-grid size-[1em] shrink-0 place-items-center align-[-0.125em] ${className}`}>
      {names.map((n) => (
        <span
          key={n}
          className={`col-start-1 row-start-1 inline-flex transition-[opacity,filter,scale] duration-[160ms] ease-out ${
            n === name ? "scale-100 opacity-100 blur-0" : "scale-90 opacity-0 blur-[4px]"
          }`}
        >
          <Icon name={n} weight={weight} />
        </span>
      ))}
    </span>
  );
}
