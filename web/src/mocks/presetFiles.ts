import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import type { components } from "@/lib/api/types";

type Preset = components["schemas"]["Preset"];
type Screen = components["schemas"]["Screen"];

// Server/Node only. Reads the real preset files (config/presets/*.json, WT-04 + WT-10) at run
// time, with `id` = file stem as the API does. Read with fs rather than imported, because
// Turbopack won't bundle files outside web/.
// turbopackIgnore: mock-only run-time reads; nothing here should be traced into a build.
export const PRESETS_DIR = path.resolve(/*turbopackIgnore: true*/ process.cwd(), "..", "config", "presets");

/** Fill the DSL defaults the files may omit, so mocks see the screen the API would. */
function withDefaults(s: Screen): Screen {
  return { ...s, limit: s.limit ?? 100, near_misses: s.near_misses ?? true };
}

export async function loadPresetFiles(dir: string = PRESETS_DIR): Promise<Preset[]> {
  const names = (await readdir(/*turbopackIgnore: true*/ dir)).filter((n) => n.endsWith(".json")).sort();
  return Promise.all(
    names.map(async (name) => {
      const raw = JSON.parse(await readFile(path.join(/*turbopackIgnore: true*/ dir, name), "utf8")) as Omit<Preset, "id">;
      return { ...raw, id: name.replace(/\.json$/, ""), screen: withDefaults(raw.screen) };
    }),
  );
}
