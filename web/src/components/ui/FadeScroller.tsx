"use client";

import { useRef, type ReactNode } from "react";
import { useScrollEdges } from "@/lib/useScrollEdges";

/** A horizontal scroller whose clipped edges fade out (useScrollEdges + `.fade-x`). Focusable, so
 * keyboard users can scroll it even when it holds no controls. */
export function FadeScroller({ children, className = "", ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  const ref = useRef<HTMLDivElement>(null);
  useScrollEdges(ref);
  return (
    <div ref={ref} tabIndex={0} className={`fade-x overflow-x-auto ${className}`} {...rest}>
      {children}
    </div>
  );
}
