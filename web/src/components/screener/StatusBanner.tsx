import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/client";

/**
 * API-down / no-build / error banner above the results (SPEC §3.3 states). Says what happened and
 * what is on screen: the last confirmed results, or a preview from this build's data that the
 * server hasn't confirmed.
 */
export function StatusBanner({
  error,
  keptStale = false,
  preview = false,
}: {
  error: unknown;
  /** Older results are still on screen, dimmed. */
  keptStale?: boolean;
  /** A live preview is on screen (computed in the browser, not yet confirmed by the server). */
  preview?: boolean;
}) {
  if (!error) return null;
  const kind = error instanceof ApiError ? error.kind : "http";
  if (kind === "no_build") {
    return (
      <div role="alert" className="space-y-1 rounded-panel border-l-2 border-caution bg-paper p-panel">
        <p className="text-prose text-ink">No build yet.</p>
        <p className="text-label text-ink-soft">
          Run <code className="font-code text-forest">glint refresh</code> first, then reload.
        </p>
      </div>
    );
  }
  const shown = preview
    ? "These results are a preview from this build's data, greyed out until the server confirms them. "
    : keptStale
      ? "Showing the last results, greyed out until it is back. "
      : "";
  const { title, next } = describeFailure(error, kind);
  return (
    <div role="alert" className="space-y-1 rounded-panel border-l-2 border-neg bg-paper p-panel">
      <p className="text-prose text-ink">{title}</p>
      <p className="text-label text-ink-soft">
        {kind === "network" ? shown : ""}
        {error instanceof Error ? error.message : String(error)}
      </p>
      {next && <p className="text-label text-ink-soft">{next}</p>}
    </div>
  );
}

/** What happened, in a heading, and what to do next (Phase 4.13: errors give directions). */
function describeFailure(error: unknown, kind: "network" | "no_build" | "http"): { title: string; next: ReactNode } {
  if (kind === "network")
    return {
      title: "Can't reach the Glint API",
      next: (
        <>
          Check that the API is running (<code className="font-code text-forest">make dev-api</code>), then reload.
        </>
      ),
    };
  const code = error instanceof ApiError ? error.body?.error : undefined;
  switch (code) {
    case "UNKNOWN_TICKER":
      return { title: "No company with that ticker", next: "Search by company name with / or go back to the screener." };
    case "UNKNOWN_PRESET":
      return { title: "That preset doesn't exist", next: "Pick one from the Presets page." };
    case "UNKNOWN_METRIC":
    case "INVALID_SCREEN":
      return { title: "The server couldn't run this screen", next: "Undo the last change, or remove the filter it names." };
    case "SCHEMA_MISMATCH":
      return { title: "The app and the API are out of step", next: "Reload the page. If it keeps happening, restart the API." };
    default:
      return { title: "Something failed on the server", next: "Try again in a moment. If it keeps happening, check the API's log." };
  }
}
