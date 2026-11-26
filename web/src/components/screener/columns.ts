import type { Unit } from "@/lib/format";
import { plainText, UNIT_LABEL } from "@/lib/labels";
import type { MetricDefinition } from "@/lib/screen/types";

// Result columns: registry metrics plus the contract's categorical fields and rank_score.
export type ColumnDef = { id: string; label: string; unit: Unit; numeric: boolean; definition: string | null };

const FIXED: Record<string, Omit<ColumnDef, "id">> = {
  ticker: { label: "Ticker", unit: "text", numeric: false, definition: null },
  name: { label: "Name", unit: "text", numeric: false, definition: null },
  sector: { label: "Sector", unit: "text", numeric: false, definition: "Glint's sector, from the company's SIC code." },
  exchange: { label: "Exchange", unit: "text", numeric: false, definition: null },
  kind: { label: "Kind", unit: "text", numeric: false, definition: null },
  rank_score: { label: "Score", unit: "score", numeric: true, definition: "How the company ranks on this screen's ranking metrics, from 0 to 1 (higher is better). Hover the column's header for the method." },
};

export function columnDef(id: string, metrics: Map<string, MetricDefinition>): ColumnDef {
  const fixed = FIXED[id];
  if (fixed) return { id, ...fixed };
  const m = metrics.get(id);
  if (!m) return { id, label: id, unit: "text", numeric: false, definition: null };
  return {
    id,
    label: m.name,
    unit: m.unit,
    numeric: m.unit !== "text" && m.unit !== "bool",
    definition: `${plainText(m.definition)} · ${m.basis.toUpperCase()} · ${UNIT_LABEL[m.unit]}${m.tier === "price" ? " · needs a market price" : ""}`,
  };
}
