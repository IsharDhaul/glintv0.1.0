import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NOTE_DISPLAY } from "@/lib/notes";
import { CLOSING, INTRO, METHODOLOGY, SECTOR_OVERRIDES } from "./methodology";

// The /about copy (this folder) and docs/methodology.md say the same thing, and the config values
// the copy quotes match config/ (principle 8: the numbers live in config; the copy only repeats them).

const REPO = path.resolve(__dirname, "..", "..", "..");
const read = (rel: string) => readFileSync(path.join(REPO, rel), "utf8");
const allText = [INTRO, CLOSING, ...METHODOLOGY.flatMap((s) => [s.title, ...s.blocks.map((b) => JSON.stringify(b))])].join("\n");

describe("methodology copy", () => {
  it("has the same section headings as docs/methodology.md, in order", () => {
    const md = read("docs/methodology.md");
    const headings = [...md.matchAll(/^## (.+)$/gm)].map((m) => m[1]);
    expect(METHODOLOGY.map((s) => s.title)).toEqual(headings);
  });

  it("covers every section the brief requires", () => {
    const ids = METHODOLOGY.map((s) => s.id);
    for (const id of [
      "data-sources-and-tiers",
      "universe-rules",
      "period-rules",
      "applicability-matrix",
      "missing-and-not-meaningful-values",
      "sectors",
      "foreign-filer-limits",
      "survivorship-and-look-ahead",
    ]) {
      expect(ids).toContain(id);
    }
    expect(CLOSING).toContain("Not investment advice.");
  });

  it("explains every null reason code", () => {
    for (const code of Object.keys(NOTE_DISPLAY)) expect(allText).toContain(`\`${code}\``);
  });

  it("quotes the config values it mentions correctly", () => {
    const thresholds = read("config/thresholds.yaml");
    const num = (key: string) => Number(new RegExp(`^\\s*${key}:\\s*([\\d.]+)`, "m").exec(thresholds)?.[1]);
    expect(allText).toContain(`more than ${num("stale_annual_report_months")} months old`);
    expect(allText).toContain(`fewer than ${num("small_peer_group_min")})`);
    expect(allText).toContain(`within ${num("average_instant_window_days")} days`);
    expect(allText).toContain(`the ${Math.round(num("roic_statutory_tax_rate") * 100)}% statutory tax rate`);
    const schema = JSON.parse(read("contracts/screen.schema.json")) as {
      $defs: {
        Universe: {
          properties: { avg_dollar_volume_min: { default: number } };
        };
      };
    };
    expect(schema.$defs.Universe.properties.avg_dollar_volume_min.default).toBe(1_000_000);
    expect(allText).toContain("default $1M");
  });

  it("sorts each universe rule into the list the DSL defaults actually put it in", () => {
    // Universe honesty (principle 6): "left out by default" must match the Universe defaults.
    const universe = METHODOLOGY.find((s) => s.id === "universe-rules")!;
    const lists = universe.blocks.filter((b) => b.kind === "ul");
    const listFor = (lead: string) => JSON.stringify(lists.find((b) => b.lead?.includes(lead))?.items ?? []);
    const leftOut = listFor("Left out by default");
    const included = listFor("Included but labelled");
    const u = (
      JSON.parse(read("contracts/screen.schema.json")) as {
        $defs: { Universe: { properties: Record<string, { default?: unknown }> } };
      }
    ).$defs.Universe.properties;
    const place = (on: boolean) => (on ? included : leftOut);
    expect(place(u.include_stale?.default === true)).toContain("15 months old");
    expect(place(u.include_foreign_filers?.default === true)).toContain("Foreign private issuers");
    expect(place(u.include_no_facts?.default === true)).toContain("no XBRL financial facts");
    expect(leftOut).toContain("average daily dollar volume floor");
    // Python's default_factory isn't in the JSON Schema: these mirror Universe.exclude_kinds.
    for (const kind of ["SPACs", "Funds", "Shell companies", "no listed common stock"]) expect(leftOut).toContain(kind);
  });

  it("lists every manual sector override, here and in docs/methodology.md", () => {
    const yaml = read("config/sector_overrides.yaml");
    const tickers = [...yaml.matchAll(/^\s*-\s*ticker:\s*(\S+)/gm)].map((m) => m[1]);
    expect(SECTOR_OVERRIDES.map((o) => o.ticker).sort()).toEqual(tickers.sort());
    const md = read("docs/methodology.md");
    if (tickers.length === 0) expect(md).toContain("There are none at the moment.");
    else for (const t of tickers) expect(md).toContain(`\`${t}\``);
  });

  it("never claims returns", () => {
    expect(allText).not.toMatch(/outperform|beat the market|returns of/i);
  });
});
