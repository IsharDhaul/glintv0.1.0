"use client";

import { useMeta } from "@/lib/api/hooks";
import { SyntheticBanner } from "./SyntheticBanner";

/**
 * The banner for a synthetic build served by the real API (`glint fixtures synthetic`, then
 * `make dev`): real mode, but the data isn't real, and `/api/meta` says so. Mock mode shows the
 * banner from the layout before any request, so this one stays out of its way.
 */
export function SyntheticBuildBanner() {
  const meta = useMeta();
  return meta.data?.synthetic ? <SyntheticBanner /> : null;
}
