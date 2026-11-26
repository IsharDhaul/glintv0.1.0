import { describe, expect, it } from "vitest";
import metrics from "../../mocks/metrics.json";
import { plainText } from "./labels";

describe("plainText", () => {
  it("rewrites reason codes, spec sections and config paths in registry prose", () => {
    expect(plainText("Null (NEGATIVE_DENOMINATOR) if EBIT ≤ 0.")).toBe("Not meaningful if EBIT ≤ 0.");
    expect(plainText("STALE_DATA if the last bar is old.")).toBe("Marked stale if the last bar is old.");
    expect(plainText("Number of flags raised (§2.10).")).toBe("Number of flags raised.");
    expect(plainText("Until F20 (FX + ADR ratios): null with FOREIGN_PRICE_BASIS unless it files a 40-F (§4.3 rule 13: Canadian issuers list directly).")).toBe(
      "Until currency and ADR conversion is supported: not meaningful unless it files a 40-F (Canadian issuers list directly).",
    );
  });

  it("leaves no internal token in any live metric's text", () => {
    for (const m of metrics.metrics) {
      const texts = [m.definition, ...Object.values(m.applicability.notes as Record<string, string>), m.tells_you ?? "", m.misleads ?? ""];
      for (const t of texts) expect(plainText(t), m.id).not.toMatch(/\b[A-Z]{2,}(?:_[A-Z]+)+\b|§|config\/|\bF20\b|metric_history/);
    }
  });
});
