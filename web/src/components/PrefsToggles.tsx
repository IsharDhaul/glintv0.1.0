"use client";

import { useSyncExternalStore } from "react";
import { Menu } from "@/components/ui/Menu";
import { sendCommand } from "@/lib/commands";
import { applyPref, DENSITY_KEY, type Density } from "@/lib/prefs";

function useHtmlAttr<T extends string>(attr: "density", fallback: T): T {
  return useSyncExternalStore(
    (notify) => {
      const obs = new MutationObserver(notify);
      obs.observe(document.documentElement, { attributes: true, attributeFilter: [`data-${attr}`] });
      return () => obs.disconnect();
    },
    () => (document.documentElement.dataset[attr] as T | undefined) ?? fallback,
    () => fallback,
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-control border border-sand-soft/60 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`h-6 rounded-control px-2 text-label transition-colors duration-150 ease-out ${
            value === o.value ? "bg-on-forest text-forest" : "text-sand-soft hover:text-on-forest"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function DensityToggle() {
  const density = useHtmlAttr<Density>("density", "compact");
  return (
    <Segmented
      label="Density"
      value={density}
      options={[
        { value: "compact", label: "Compact" },
        { value: "comfortable", label: "Comfortable" },
      ]}
      onChange={(v) => applyPref("density", v, DENSITY_KEY)}
    />
  );
}

/** Settings on the header band: row density and the keyboard map (there is one theme). */
export function SettingsMenu() {
  const density = useHtmlAttr<Density>("density", "compact");
  return (
    <Menu
      label="Settings"
      variant="band"
      items={[
        { id: "compact", label: "Compact rows", checked: density === "compact", onSelect: () => applyPref("density", "compact", DENSITY_KEY) },
        { id: "comfortable", label: "Comfortable rows", checked: density === "comfortable", onSelect: () => applyPref("density", "comfortable", DENSITY_KEY) },
        { id: "shortcuts", label: "Keyboard shortcuts", hint: "Press ? anywhere", onSelect: () => sendCommand({ kind: "show-shortcuts" }) },
      ]}
    />
  );
}
