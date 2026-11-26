import { Icon } from "@/components/ui/Icon";
import { MISSING_GLYPH, NOTE_DISPLAY, NOT_MEANINGFUL_GLYPH, type CellNote } from "@/lib/notes";
import { Tooltip } from "./Tooltip";

/** A null cell: "—" for missing, "n/m" for not meaningful, with the reason in a tooltip. */
export function NullValue({ note, fallbackReason }: { note: CellNote | null | undefined; fallbackReason?: string }) {
  const display = note ? NOTE_DISPLAY[note.code] : null;
  const glyph = display?.shown === "n/m" ? NOT_MEANINGFUL_GLYPH : MISSING_GLYPH;
  const tip = display ? (
    <>
      <span className="block font-medium">{display.label}</span>
      {note?.message && <span className="block text-muted">{note.message}</span>}
    </>
  ) : (
    (fallbackReason ?? "No value and no reason recorded")
  );
  return (
    <Tooltip tip={tip}>
      <span className="text-muted">{glyph}</span>
    </Tooltip>
  );
}

/** Info marker for a real value that carries an info note (DERIVED_INPUT, ASSUMED_TAX_RATE, INPUT_EXCLUDES). */
export function InfoMark({ note }: { note: CellNote }) {
  return (
    <Tooltip
      tip={
        <>
          <span className="block font-medium">{NOTE_DISPLAY[note.code].label}</span>
          <span className="block text-muted">{note.message}</span>
        </>
      }
    >
      <span role="img" aria-label="Note" className="ml-0.5 text-meta text-forest">
        <Icon name="info" />
      </span>
    </Tooltip>
  );
}
