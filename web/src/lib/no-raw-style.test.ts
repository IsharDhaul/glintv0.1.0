import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Acceptance (docs/ui-spec.md §1.6): components style with tokens only. Colours, sizes and type
// come from globals.css; the Visual standard bans all-caps labels and letter-spacing.

const SRC = path.resolve(__dirname, "..");
const RULES: [RegExp, string][] = [
  [/#[0-9a-fA-F]{3,8}\b/, "raw hex colour"],
  [/\brgba?\(/, "raw rgb colour"],
  [/\b(?:text|bg|border|fill|stroke)-\[(?:#|rgb|\d+px)/, "arbitrary colour or size"],
  [/\buppercase\b/, "all-caps label"],
  [/\btracking-/, "letter-spacing"],
  [/\bfont-mono\b/, "font-mono (use font-code for code only)"],
  [/\btext-(?:xs|sm|base|lg|xl|2xl|3xl)\b/, "raw text size (use the type scale)"],
  [/\b(?:bg|text|border)-(?:white|black|gray|slate|zinc|neutral|stone|red|green|blue|amber|yellow)-?/, "palette colour outside the tokens"],
  [/[✕▸▾ⓘ🔗⤓▲▼◆⚠✓✗⚑]/u, "text glyph as an icon (use components/ui/Icon)"],
  [/\b\d+vh\b|\b(?:min-|max-)?h-screen\b/, "vh units (use dvh: 100vh is wrong in Safari)"],
  [/\brounded(?:-(?:sm|md|lg|xl|2xl))?\b(?!-)/, "untokened radius (use rounded-control / -panel / -sheet / -in-sheet / -full)"],
  [/(?<!repeating-)(?:linear|radial|conic)-gradient\((?![^)]*\bin okl(?:ch|ab)\b)/, "gradient without `in oklch` (it greys out in the middle)"],
];
// Data that legitimately carries a hex-like string or a swatch value.
const EXEMPT = new Set([path.join(SRC, "app", "dev", "kitchen-sink", "KitchenSink.tsx")]);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return /\.tsx$/.test(name) ? [p] : [];
  });
}

describe("no raw styling", () => {
  it("components use tokens, the type scale, no caps and no tracking", () => {
    const offenders: string[] = [];
    for (const file of files(SRC)) {
      if (EXEMPT.has(file)) continue;
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (/^\s*(\/\/|\*)/.test(line)) return; // comments
          for (const [re, why] of RULES) if (re.test(line)) offenders.push(`${path.relative(SRC, file)}:${i + 1}: ${why}: ${line.trim().slice(0, 120)}`);
        });
    }
    expect(offenders).toEqual([]);
  });
});
