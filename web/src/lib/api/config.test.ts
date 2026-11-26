import { describe, expect, it } from "vitest";
import { apiBaseUrl, DEFAULT_API_URL, isMockMode } from "./config";

describe("apiBaseUrl", () => {
  it("defaults to localhost:8000", () => {
    expect(apiBaseUrl({})).toBe(DEFAULT_API_URL);
  });
  it("strips trailing slashes", () => {
    expect(apiBaseUrl({ NEXT_PUBLIC_GLINT_API_URL: "http://localhost:8008/" })).toBe(
      "http://localhost:8008",
    );
  });
});

describe("isMockMode", () => {
  it("is on only for 1", () => {
    expect(isMockMode({ NEXT_PUBLIC_GLINT_MOCK: "1" })).toBe(true);
    expect(isMockMode({ NEXT_PUBLIC_GLINT_MOCK: "0" })).toBe(false);
    expect(isMockMode({})).toBe(false);
  });
});
