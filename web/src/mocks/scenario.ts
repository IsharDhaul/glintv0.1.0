// Mock scenarios let the UI states (SPEC §3.3) be exercised on purpose:
//   ?mock=down     every API call fails at the network level ("API down")
//   ?mock=nobuild  every call returns 503 NO_BUILD ("run glint refresh first")
//   ?mock=empty    screens return zero results
//   ?mock=slow     every call waits 1.5 s (loading states)
//   ?mock=ok       back to normal
// The choice sticks for the tab (sessionStorage) so client navigation keeps it.

export const SCENARIOS = ["ok", "down", "nobuild", "empty", "slow"] as const;
export type Scenario = (typeof SCENARIOS)[number];

const KEY = "glint.mockScenario";

export function readScenario(): Scenario {
  if (typeof window === "undefined") return "ok";
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("mock");
    if (fromUrl && (SCENARIOS as readonly string[]).includes(fromUrl)) {
      sessionStorage.setItem(KEY, fromUrl);
      return fromUrl as Scenario;
    }
    const stored = sessionStorage.getItem(KEY);
    if (stored && (SCENARIOS as readonly string[]).includes(stored)) return stored as Scenario;
  } catch {
    // Storage blocked: URL only.
  }
  return "ok";
}
