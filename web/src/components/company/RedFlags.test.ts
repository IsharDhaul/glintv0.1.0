import { describe, expect, it } from "vitest";
import { loadPresetFiles } from "@/mocks/presetFiles";
import { isRedFlagPreset } from "./RedFlags";

describe("red-flag presets", () => {
  it("the naming convention picks exactly the red-flag screens in config/presets", async () => {
    const presets = await loadPresetFiles();
    expect(presets.filter((p) => isRedFlagPreset(p.name)).map((p) => p.id).sort()).toEqual(["accruals-risk", "dilution-watch"]);
  });
});
