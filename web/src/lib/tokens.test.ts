import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// The colour tokens in globals.css, checked as the browser will render them: OKLCH → sRGB, alpha
// tokens composited over each surface, WCAG 2.x contrast. The Visual standard's table
// (docs/design-direction.md) must stay true of these numbers.

const css = readFileSync(path.resolve(__dirname, "../app/globals.css"), "utf8");
const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));

type Lin = [number, number, number];
type Token = { L: number; C: number; H: number; alpha: number };

function token(name: string): Token {
  const m = new RegExp(`--${name}:\\s*oklch\\(([\\d.]+)%\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*/\\s*([\\d.]+))?\\)`).exec(root);
  if (!m) throw new Error(`--${name} is not an oklch() token`);
  return { L: Number(m[1]) / 100, C: Number(m[2]), H: Number(m[3]), alpha: m[4] === undefined ? 1 : Number(m[4]) };
}

function toLinear({ L, C, H }: Token): Lin {
  const a = C * Math.cos((H * Math.PI) / 180);
  const b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return [
    clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

// Alpha compositing happens on gamma-encoded sRGB in browsers.
const enc = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const dec = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
function over(fg: Token, bg: Lin): Lin {
  const f = toLinear(fg);
  return f.map((c, i) => dec(enc(c) * fg.alpha + enc(bg[i] as number) * (1 - fg.alpha))) as Lin;
}
const lum = (c: Lin) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
const contrast = (a: Lin, b: Lin) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);

const SURFACES = ["sand", "paper", "dune"].map((n) => [n, toLinear(token(n))] as const);
const TEXT = ["ink", "ink-soft", "muted", "forest", "purple-ink", "pos", "neg", "caution"];
const NON_TEXT = ["line-strong", "nodata"];

describe("colour tokens", () => {
  it.each(TEXT)("text token %s is ≥ 4.5:1 on sand, paper and dune", (name) => {
    for (const [surface, bg] of SURFACES) expect(contrast(over(token(name), bg), bg), `${name} on ${surface}`).toBeGreaterThanOrEqual(4.5);
  });

  it.each(NON_TEXT)("non-text token %s is ≥ 3:1 on sand, paper and dune", (name) => {
    for (const [surface, bg] of SURFACES) expect(contrast(over(token(name), bg), bg), `${name} on ${surface}`).toBeGreaterThanOrEqual(3);
  });

  it("purple (fills only) is ≥ 3:1 on sand and paper", () => {
    for (const [surface, bg] of SURFACES.filter(([n]) => n !== "dune")) expect(contrast(over(token("purple"), bg), bg), surface).toBeGreaterThanOrEqual(3);
  });

  it("text on the forest band and the banner is ≥ 4.5:1", () => {
    const forest = toLinear(token("forest"));
    expect(contrast(toLinear(token("paper")), forest)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(toLinear(token("sand-soft")), forest)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(toLinear(token("ink")), toLinear(token("banner")))).toBeGreaterThanOrEqual(4.5);
  });

  it("up, down and caution share one lightness, so none reads heavier", () => {
    const Ls = ["pos", "neg", "caution"].map((n) => token(n).L);
    expect(Math.max(...Ls) - Math.min(...Ls)).toBeLessThanOrEqual(0.005);
  });

  it("borders are alpha over ink, so they blend into every surface", () => {
    for (const n of ["line", "line-strong"]) {
      const t = token(n);
      expect(t.alpha, n).toBeLessThan(1);
      expect([t.L, t.C, t.H]).toEqual([token("ink").L, token("ink").C, token("ink").H]);
    }
  });

  it("the user's three anchors are exact", () => {
    const hex = (t: Token) =>
      toLinear(t)
        .map((c) => Math.round(enc(c) * 255).toString(16).padStart(2, "0"))
        .join("")
        .toUpperCase();
    expect(hex(token("forest"))).toBe("1F3D2B");
    expect(hex(token("sand"))).toBe("E8DCC4");
    expect(hex(token("purple"))).toBe("8B5CF6");
  });
});
