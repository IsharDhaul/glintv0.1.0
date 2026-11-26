import { formulaParts } from "@/lib/metricText";

/**
 * A metric's formula: a symbolic expression in Plex Mono (it names metric ids), a formula written
 * as a sentence in the word face, and a worded aside after it in the word face either way.
 */
export function Formula({ formula, className = "" }: { formula: string; className?: string }) {
  const { expr, note, code } = formulaParts(formula);
  return (
    <span className={className}>
      <span className={code ? "font-code" : "font-words"}>{expr}</span>
      {note && <span className="font-words text-muted"> ({note})</span>}
    </span>
  );
}
