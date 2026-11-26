import { Formula } from "@/components/ui/Formula";
import { BASIS_LABEL, UNIT_LABEL } from "@/lib/labels";
import { splitDefinition } from "@/lib/metricText";
import type { MetricDefinition } from "@/lib/screen/types";
import type { ReactNode } from "react";

/**
 * A metric's tooltip body, the same everywhere: what it tells you, the formula (mono), then basis
 * and unit. `extra` adds a line (a price date, say); `more` says where the full entry is.
 */
export function MetricTip({ def, extra, more = true }: { def: MetricDefinition; extra?: ReactNode; more?: boolean }) {
  const { formula } = splitDefinition(def.definition);
  return (
    <>
      {def.tells_you && <span className="block text-ink-soft">{def.tells_you}</span>}
      <Formula formula={formula} className="mt-1 block text-meta text-ink-soft" />
      <span className="mt-1 block text-muted">
        {BASIS_LABEL[def.basis]}, {UNIT_LABEL[def.unit]}
        {extra ? <>, {extra}</> : null}
      </span>
      {more && <span className="mt-1 block text-muted">Full entry in the metric dictionary.</span>}
    </>
  );
}
