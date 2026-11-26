"use client";

import { useEffect, useRef, useState } from "react";

/**
 * A count that ticks to its new value over `ms` (≤ 200ms, Visual standard) instead of jumping,
 * and reports whether it just changed (for a short purple underline). The first value shows at
 * once; reduced motion shows every value at once.
 */
export function useTickedNumber(value: number, ms = 200): { shown: number; changed: boolean } {
  const [shown, setShown] = useState(value);
  const [changed, setChanged] = useState(false);
  const from = useRef(value);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      from.current = value;
      return;
    }
    const start = from.current;
    from.current = value;
    if (start === value) return;
    const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const p = reduce ? 1 : Math.min(1, (t - t0) / ms);
      const eased = 1 - (1 - p) ** 3;
      setShown(Math.round(start + (value - start) * eased));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    setChanged(true);
    const off = setTimeout(() => setChanged(false), 1500);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(off);
    };
  }, [value, ms]);

  return { shown, changed };
}
