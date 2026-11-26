import { describe, expect, it } from "vitest";
import { displayName } from "./names";

describe("displayName", () => {
  it.each([
    ["ADOBE INC.", "Adobe"],
    ["UPWORK, INC", "Upwork"],
    ["Nutex Health Inc.", "Nutex Health"],
    ["MERCADOLIBRE INC", "Mercadolibre"],
    ["AMC NETWORKS INC", "AMC Networks"],
    ["BANK OF AMERICA CORP /DE/", "Bank of America"],
    ["Alight, Inc. / Delaware", "Alight"],
    ["Booking Holdings Inc.", "Booking"],
    ["COCA-COLA CO", "Coca-Cola"],
    ["eBay Inc.", "eBay"],
    ["Synthetic Co 0001", "Synthetic Co 0001"],
  ])("%s → %s", (raw, want) => {
    expect(displayName(raw)).toBe(want);
  });
});
