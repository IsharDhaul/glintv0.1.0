import type { components } from "./api/types";

export type NoteCode = components["schemas"]["NoteCode"];
export type CellNote = components["schemas"]["CellNote"];

/** How each note code renders (SPEC §2.4 "Null reason codes"). `info` codes annotate a real value. */
export const NOTE_DISPLAY: Record<NoteCode, { shown: "missing" | "n/m" | "info"; label: string }> = {
  MISSING_INPUT: { shown: "missing", label: "A required input isn't in the filings" },
  NEGATIVE_DENOMINATOR: { shown: "n/m", label: "Not meaningful: the denominator is zero or negative" },
  NOT_APPLICABLE_SECTOR: { shown: "n/m", label: "Not meaningful for this sector" },
  FOREIGN_PRICE_BASIS: { shown: "n/m", label: "Not meaningful: foreign filer's share basis or currency doesn't match the US price" },
  INSUFFICIENT_HISTORY: { shown: "missing", label: "Not enough history yet" },
  STALE_DATA: { shown: "missing", label: "Inputs are older than the freshness limit" },
  NO_INTEREST_EXPENSE: { shown: "n/m", label: "Not meaningful: no interest expense reported" },
  // Labels name the rule, not its threshold: the numbers live in config/thresholds.yaml and the
  // API message (shown under the label) states them (review fix, principle 8).
  SMALL_PEER_GROUP: { shown: "missing", label: "Too few companies in the sector for a sector comparison" },
  DERIVED_INPUT: { shown: "info", label: "Uses a derived input" },
  ASSUMED_TAX_RATE: { shown: "info", label: "Uses the statutory tax rate" },
  INPUT_EXCLUDES: { shown: "info", label: "An input leaves out an item the filing doesn't place" },
};

export const MISSING_GLYPH = "—";
export const NOT_MEANINGFUL_GLYPH = "n/m";
