import { compressToEncodedURIComponent, decompressFromEncodedURIComponent } from "lz-string";
import type { Screen } from "./types";

// Screen JSON ↔ URL-safe string (SPEC §2.12). The variant matches what the API decodes for
// `/api/companies/{ticker}?screen=` (lz-string compressToEncodedURIComponent).

export function encodeScreen(screen: Screen): string {
  return compressToEncodedURIComponent(JSON.stringify(screen));
}

/** The screen, or null if the text isn't a compressed Screen (bad link, other app's param). */
export function decodeScreen(text: string | null | undefined): Screen | null {
  if (!text) return null;
  try {
    const json = decompressFromEncodedURIComponent(text);
    if (!json) return null;
    const s = JSON.parse(json) as Partial<Screen> | null;
    if (!s || typeof s !== "object" || s.dsl_version !== 1 || typeof s.name !== "string") return null;
    // Keep the link's key order (defaults only fill gaps), so an unchanged screen re-encodes identically.
    return { ...s, limit: s.limit ?? 100, near_misses: s.near_misses ?? true } as Screen;
  } catch {
    return null;
  }
}
