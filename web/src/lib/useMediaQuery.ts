"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a media query matches, kept in sync as the window resizes. `serverValue` is what the
 * server (and the first hydrated render) assumes: desktop, so wide screens never shift on load.
 */
export function useMediaQuery(query: string, serverValue: boolean): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}

/** Below 1024px the filter rail becomes a summary bar and a sheet (docs/ui-spec.md §2). */
export const WIDE = "(min-width: 64rem)";
/** Below 768px: phone layout (results first, compact table, one-line sieve). */
export const PHONE = "(max-width: 47.99rem)";
