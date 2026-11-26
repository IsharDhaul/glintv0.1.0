"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { decodeSnapshot, type Store } from "@/lib/data/snapshot";
import { encodeScreen } from "@/lib/screen/codec";
import type { Screen, Sector } from "@/lib/screen/types";
import { api, ApiError, unwrap } from "./client";
import type { components } from "./types";

type Within = components["schemas"]["Within"];

// Build-scoped data changes once a day at most: keep it fresh for the session.
const STATIC = { staleTime: Infinity } as const;

export const queryKeys = {
  meta: ["meta"] as const,
  metrics: ["metrics"] as const,
  sectors: ["sectors"] as const,
  presets: ["presets"] as const,
  preset: (id: string) => ["preset", id] as const,
  screen: (s: Screen) => ["screen", s] as const,
  distribution: (metric: string, within: Within, sector: Sector | null) => ["distribution", metric, within, sector] as const,
  search: (q: string) => ["search", q] as const,
  company: (ticker: string, screen: string | null) => ["company", ticker, screen] as const,
  history: (ticker: string, metric: string) => ["history", ticker, metric] as const,
  snapshot: ["snapshot"] as const,
};

export function useMeta() {
  return useQuery({ queryKey: queryKeys.meta, queryFn: () => unwrap(api.GET("/api/meta")), ...STATIC });
}

export function useMetrics() {
  return useQuery({ queryKey: queryKeys.metrics, queryFn: () => unwrap(api.GET("/api/metrics")), ...STATIC });
}

export function useSectors() {
  return useQuery({ queryKey: queryKeys.sectors, queryFn: () => unwrap(api.GET("/api/sectors")), ...STATIC });
}

export function usePresets() {
  return useQuery({ queryKey: queryKeys.presets, queryFn: () => unwrap(api.GET("/api/presets")), ...STATIC });
}

export function usePreset(id: string | null) {
  return useQuery({
    queryKey: queryKeys.preset(id ?? ""),
    queryFn: () => unwrap(api.GET("/api/presets/{preset_id}", { params: { path: { preset_id: id ?? "" } } })),
    enabled: id !== null,
    ...STATIC,
  });
}

/** Runs a screen. While a new one loads, the previous response stays (dimmed by the UI). */
export function useScreen(screen: Screen | null) {
  return useQuery({
    queryKey: queryKeys.screen(screen as Screen),
    queryFn: () => unwrap(api.POST("/api/screen", { body: screen as Screen })),
    enabled: screen !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useDistribution(metric: string | null, within: Within = "universe", sector: Sector | null = null) {
  return useQuery({
    queryKey: queryKeys.distribution(metric ?? "", within, sector),
    queryFn: () =>
      unwrap(api.GET("/api/distribution", { params: { query: { metric: metric ?? "", within, sector } } })),
    enabled: metric !== null,
    ...STATIC,
  });
}

export function useSearch(q: string) {
  const query = q.trim();
  return useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => unwrap(api.GET("/api/search", { params: { query: { q: query } } })),
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/** One company (SPEC §2.9). With a screen that has filters, the API adds `why_passed`. */
export function useCompany(ticker: string | null, screen: Screen | null = null) {
  const encoded = screen && (screen.filters?.children?.length ?? 0) > 0 ? encodeScreen(screen) : null;
  return useQuery({
    queryKey: queryKeys.company(ticker ?? "", encoded),
    queryFn: () =>
      unwrap(
        api.GET("/api/companies/{ticker}", {
          params: { path: { ticker: ticker ?? "" }, query: encoded ? { screen: encoded } : undefined },
        }),
      ),
    enabled: ticker !== null,
    // Same company, new screen: keep showing it while why_passed refreshes.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[1] === ticker ? prev : undefined),
    ...STATIC,
  });
}

export function useHistory(ticker: string | null, metric: string) {
  return useQuery({
    queryKey: queryKeys.history(ticker ?? "", metric),
    queryFn: () =>
      unwrap(
        api.GET("/api/companies/{ticker}/history", {
          params: { path: { ticker: ticker ?? "" }, query: { metric } },
        }),
      ),
    enabled: ticker !== null,
    ...STATIC,
  });
}

/** CSV export (SPEC §2.12). The filename comes from Content-Disposition when the API sends one. */
export async function exportScreen(screen: Screen): Promise<{ blob: Blob; filename: string }> {
  let res;
  try {
    res = await api.POST("/api/screen/export", { body: screen, parseAs: "blob" });
  } catch {
    throw new ApiError("network", null, null, "Can't reach the API to export.");
  }
  if (!res.response.ok || !(res.data instanceof Blob)) {
    throw new ApiError("http", res.response.status, null, `Export failed: ${res.response.status}`);
  }
  const cd = res.response.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(cd);
  return { blob: res.data, filename: match?.[1] ?? fallbackFilename(screen.name) };
}

export function fallbackFilename(name: string, today = new Date()): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "screen";
  return `glint-${slug}-${today.toISOString().slice(0, 10)}.csv`;
}

/**
 * The build's metric values as columns, for the live preview (docs/interaction-architecture.md).
 * Fetched once per build (both requests carry ?build= so the browser can cache them for good).
 * Until it arrives, or if it fails, the screener runs on /api/screen alone.
 */
export function useSnapshot() {
  return useQuery<Store>({
    queryKey: queryKeys.snapshot,
    queryFn: async () => {
      const meta = await unwrap(api.GET("/api/snapshot/meta"));
      const build = meta.build_id ?? undefined;
      const res = await api.GET("/api/snapshot/values", { params: { query: { build } }, parseAs: "arrayBuffer" });
      if (!res.response.ok || !(res.data instanceof ArrayBuffer)) {
        throw new ApiError("http", res.response.status, null, `Snapshot values: ${res.response.status}`);
      }
      const served = res.response.headers.get("X-Glint-Build");
      if (served && build && served !== build) throw new ApiError("http", 409, null, "The build changed while loading; reload to pick up the new one.");
      return decodeSnapshot(meta, res.data);
    },
    ...STATIC,
    retry: 1,
  });
}

