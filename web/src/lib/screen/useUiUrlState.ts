"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { uiFromSearch, withUiParams, type UiParams } from "./url";

/**
 * The selected ticker and open drawer, kept in `?t=` and `?d=1` (docs/interaction-architecture.md):
 * they survive a reload and travel with Share. Changes *replace* the history entry, so flicking
 * through results with j/k doesn't add a Back step per company; screen edits still push.
 */
export function useUiUrlState(): UiParams & { set: (ui: UiParams) => void; update: (fn: (current: UiParams) => UiParams) => void } {
  const params = useSearchParams();
  const ui = useMemo(() => uiFromSearch(`?${params.toString()}`), [params]);
  const set = useCallback((next: UiParams) => {
    const url = `${window.location.pathname}${withUiParams(window.location.search, next)}`;
    // null state: Next.js syncs useSearchParams only for history entries it didn't write itself.
    window.history.replaceState(null, "", url);
  }, []);
  // From the address bar as it is now, not the last render: two quick pins both land.
  const update = useCallback((fn: (current: UiParams) => UiParams) => set(fn(uiFromSearch(window.location.search))), [set]);
  return { ...ui, set, update };
}
