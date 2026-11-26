import { useCallback, useLayoutEffect, useRef } from "react";

/**
 * A function whose identity never changes but always calls the latest `fn`, so memoised children
 * (the results table, near misses) don't re-render just because a parent made a new closure.
 */
export function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn);
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: A) => ref.current(...args), []);
}
