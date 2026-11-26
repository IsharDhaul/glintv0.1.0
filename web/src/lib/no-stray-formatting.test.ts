import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Acceptance: every number and date in the UI passes through format.ts (SPEC §3.3).
// This scans the source for formatting calls anywhere else.

const SRC = path.resolve(__dirname, "..");
const ALLOWED = new Set([path.join(SRC, "lib", "format.ts")]);
const FORBIDDEN = [
  /\.toFixed\(/,
  /\.toPrecision\(/,
  /\.toLocaleString\(/,
  /\.toLocaleDateString\(/,
  /\.toLocaleTimeString\(/,
  /Intl\.NumberFormat/,
  /Intl\.DateTimeFormat/,
];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.ts$/.test(name) ? [p] : [];
  });
}

describe("no stray number formatting", () => {
  it("only format.ts formats numbers and dates", () => {
    const offenders: string[] = [];
    for (const file of files(SRC)) {
      if (ALLOWED.has(file) || file.endsWith(path.join("api", "types.ts"))) continue;
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (FORBIDDEN.some((re) => re.test(line))) offenders.push(`${path.relative(SRC, file)}:${i + 1}: ${line.trim()}`);
        });
    }
    expect(offenders).toEqual([]);
  });
});
