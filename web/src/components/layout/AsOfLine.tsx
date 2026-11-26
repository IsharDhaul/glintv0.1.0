"use client";

import { ApiError } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { formatDate, formatDateTimeEt } from "@/lib/format";

/** SPEC §2.11 freshness line, shown on every page. */
export function AsOfLine() {
  const meta = useMeta();
  if (meta.error) {
    const kind = meta.error instanceof ApiError ? meta.error.kind : "http";
    return (
      <p className="text-meta text-caution" role="status">
        {kind === "no_build" ? "No build yet: run glint refresh." : kind === "network" ? "Can't reach the API, so data freshness is unknown." : "Build info didn't load. Reload to try again."}
      </p>
    );
  }
  if (!meta.data) return <p className="text-meta text-muted">Loading build info…</p>;
  const m = meta.data;
  return (
    <p className="text-meta text-muted">
      Filings as of {formatDateTimeEt(m.as_of.fundamentals)}. Prices at the close of {formatDate(m.as_of.prices)}. Build{" "}
      <span className="font-code">{m.build_id ?? "—"}</span>, built {formatDateTimeEt(m.built_at)}.
    </p>
  );
}
