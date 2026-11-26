import { Icon } from "@/components/ui/Icon";
import { formatMetric, type Unit } from "@/lib/format";
import { NOTE_DISPLAY, type CellNote } from "@/lib/notes";
import { InfoMark, NullValue } from "./NullValue";

/**
 * One metric value, display only. Nulls render "—" / "n/m" with their reason; info notes add an info mark;
 * `pp` changes get an up/down caret plus pos/neg colour (never colour alone, DESIGN.md).
 */
export function MetricValue({
  def,
  value,
  note,
  slot = false,
}: {
  def: { id: string; unit: Unit };
  value: number | boolean | string | null | undefined;
  note?: CellNote | null;
  /** Tables: put the info mark in a fixed slot left of the number, so decimals stay aligned. */
  slot?: boolean;
}) {
  if (value === null || value === undefined) return <NullValue note={note} />;
  const text = formatMetric(def, value);
  const info = note && NOTE_DISPLAY[note.code].shown === "info" ? <InfoMark note={note} /> : null;
  const slotted = slot ? <span className="inline-flex w-4 justify-start">{info}</span> : null;
  if (def.unit === "pp" && typeof value === "number" && text !== "0.0 pp") {
    const up = value > 0;
    return (
      <span className={up ? "text-pos" : "text-neg"}>
        {slotted}
        <Icon name={up ? "caret-up" : "caret-down"} className="mr-0.5" />
        {text}
        {slot ? null : info}
      </span>
    );
  }
  return (
    <span>
      {slotted}
      {text}
      {slot ? null : info}
    </span>
  );
}
