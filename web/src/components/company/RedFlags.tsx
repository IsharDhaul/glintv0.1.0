"use client";

import { usePreset, usePresets } from "@/lib/api/hooks";
import { screenCheck } from "@/lib/screen/check";
import { describeNode } from "@/lib/screen/describe";
import type { ScreenEngine } from "@/lib/screen/engine";
import { isGroup, type MetricDefinition } from "@/lib/screen/types";

/**
 * Presets written as red-flag screens: their names end "(red flags)" in config/presets. This is a
 * naming convention, pinned by a test, until the Preset contract gets a `kind` field.
 */
export function isRedFlagPreset(name: string): boolean {
  return /\(red flags\)\s*$/i.test(name);
}

/** Flag rows for every red-flag preset this company passes, with the rules it tripped. */
export function RedFlags({ engine, row, defs }: { engine: ScreenEngine | null; row: number | null; defs: Map<string, MetricDefinition> }) {
  const presets = usePresets();
  if (!engine || row === null) return null;
  const ids = (presets.data?.presets ?? []).filter((p) => isRedFlagPreset(p.name)).map((p) => p.id);
  return (
    <>
      {ids.map((id) => (
        <RedFlagPreset key={id} id={id} engine={engine} row={row} defs={defs} />
      ))}
    </>
  );
}

function RedFlagPreset({ id, engine, row, defs }: { id: string; engine: ScreenEngine; row: number; defs: Map<string, MetricDefinition> }) {
  const preset = usePreset(id);
  const p = preset.data?.preset;
  if (!p) return null;
  const check = screenCheck(p.screen, engine.evaluate(p.screen, { nearMisses: false, rank: false }).whyPassed(row));
  if (!check.inUniverse || check.filters.length === 0 || check.failed.length > 0) return null;
  const rules = check.filters.map((f) => (isGroup(f.node) ? describeNode(f.node, defs) : describeNode(f.node, defs)));
  return (
    <div className="mb-2 border-l-2 border-caution py-1 pl-3">
      <p className="max-w-prose text-prose text-ink-soft">
        Matches the <span className="text-ink">{p.name.replace(/\s*\(red flags\)\s*$/i, "")}</span> red-flag screen. Worth a closer look?
      </p>
      <p className="text-meta text-muted">{rules.join("; ")}</p>
    </div>
  );
}
