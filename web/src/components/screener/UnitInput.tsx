"use client";

import { useId, useState } from "react";
import type { Unit } from "@/lib/format";
import { inputAffix, inputText, parseInput } from "@/lib/units";

/**
 * Threshold input in display units ("15" for 15%). Converts through units.ts exactly once.
 * Valid text commits as you type; invalid text is flagged and not committed.
 */
export function UnitInput({
  unit,
  value,
  onCommit,
  label,
  placeholder,
  width = "w-16",
}: {
  unit: Unit;
  value: number | null;
  onCommit: (v: number | null) => void;
  label: string;
  placeholder?: string;
  width?: string;
}) {
  const [text, setText] = useState(() => inputText(unit, value));
  const [focused, setFocused] = useState(false);
  const errId = useId();
  // Follow outside changes (preset load, undo) unless the user is typing.
  const shown = focused ? text : inputText(unit, value);
  const invalid = shown.trim() !== "" && parseInput(unit, shown) === null;
  const { prefix, suffix } = inputAffix(unit);

  return (
    <span className="inline-flex flex-col">
      <label
        className={`flex h-ctl items-center rounded-control border bg-paper px-2 focus-within:border-forest focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-purple ${invalid ? "border-neg" : "border-line-strong"}`}
      >
        {prefix && <span className="mr-0.5 text-label text-muted">{prefix}</span>}
        <input
          aria-label={label}
          aria-invalid={invalid}
          aria-describedby={invalid ? errId : undefined}
          inputMode="decimal"
          placeholder={placeholder}
          value={shown}
          onFocus={() => {
            setText(inputText(unit, value));
            setFocused(true);
          }}
          onBlur={() => setFocused(false)}
          onChange={(e) => {
            setText(e.target.value);
            if (e.target.value.trim() === "") onCommit(null);
            else {
              const v = parseInput(unit, e.target.value);
              if (v !== null) onCommit(v);
            }
          }}
          className={`num ${width} bg-transparent text-right text-label outline-none placeholder:text-muted/60`}
        />
        {suffix && <span className="ml-1 text-label text-muted">{suffix}</span>}
      </label>
      {invalid && (
        <span id={errId} role="status" className="mt-0.5 text-meta text-neg">
          Not a number
        </span>
      )}
    </span>
  );
}
