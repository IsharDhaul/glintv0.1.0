"use client";

import { IconSwap } from "@/components/ui/IconSwap";
import { useId, useState, memo } from "react";
import { Button } from "@/components/ui/Button";
import { Menu } from "@/components/ui/Menu";
import type { components } from "@/lib/api/types";
import { UniverseControl } from "./UniverseControl";
import type { Screen } from "@/lib/screen/types";

type Universe = components["schemas"]["Universe"];
type PresetSummary = components["schemas"]["PresetSummary"];

export const Toolbar = memo(function Toolbar({
  name,
  universe,
  onUniverse,
  presets,
  onPreset,
  buildCount,
  excluded,
  onExport,
  onShare,
  compact = false,
  universeOpen = false,
  onUniverseOpen = () => {},
}: {
  name: string;
  universe: Screen["universe"];
  onUniverse: (patch: Partial<Universe>) => void;
  presets: PresetSummary[];
  onPreset: (id: string) => void;
  buildCount: number | null;
  /** Companies outside the universe: the funnel's universe step `removed`. */
  excluded: number | null;
  onExport: () => Promise<string | void>;
  onShare: () => Promise<void>;
  /** Phones: CSV and Share move into a menu. */
  compact?: boolean;
  /** The universe panel, controlled so the sieve's universe tray can open it. */
  universeOpen?: boolean;
  onUniverseOpen?: (open: boolean) => void;
}) {
  const titleId = useId();
  const [busy, setBusy] = useState<"export" | "share" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState<"export" | "share" | null>(null);

  const run = async (kind: "export" | "share", fn: () => Promise<string | void>, done: string) => {
    setBusy(kind);
    try {
      const said = await fn();
      setNotice(typeof said === "string" ? said : done);
      setDone(kind);
      setTimeout(() => setDone((d) => (d === kind ? null : d)), 1500);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : kind === "share" ? "Couldn't copy the link. Copy it from the address bar." : "Couldn't download the CSV. Try again.");
    } finally {
      setBusy(null);
      setTimeout(() => setNotice(null), 2500);
    }
  };

  return (
    // A region named by the screen, so the title and universe sit in a landmark (main starts below).
    <section aria-labelledby={titleId} className="flex flex-wrap items-center gap-2 border-b border-line bg-paper px-4 py-2">
      <h1 id={titleId} className={`mr-1 truncate text-section font-semibold text-ink ${compact ? "min-w-0 flex-1" : ""}`} title={name}>
        {name}
      </h1>
      {/* Phones: the title and actions share the first row, the universe takes the second. */}
      <div className={compact ? "order-last basis-full" : "contents"}>
        <UniverseControl
          universe={universe}
          onUniverse={onUniverse}
          excluded={excluded}
          buildCount={buildCount}
          open={universeOpen}
          onOpenChange={onUniverseOpen}
        />
      </div>
      <div className="ml-auto flex items-center gap-1">
        <span aria-live="polite" className="mr-1 text-meta text-muted">
          {notice}
        </span>
        <Menu
          label="Presets"
          items={presets.map((p) => ({ id: p.id, label: p.name, hint: p.summary, onSelect: () => onPreset(p.id) }))}
        />
        {compact ? (
          <Menu
            label="More"
            items={[
              { id: "share", label: "Copy share link", onSelect: () => void run("share", onShare, "Link copied.") },
              { id: "export", label: "Download CSV", onSelect: () => void run("export", onExport, "CSV downloaded.") },
            ]}
          />
        ) : (
          <>
            <Button onClick={() => run("export", onExport, "CSV downloaded.")} disabled={busy !== null} aria-label="Export CSV">
              <IconSwap name={done === "export" ? "check" : "download"} names={["download", "check"]} /> CSV
            </Button>
            <Button onClick={() => run("share", onShare, "Link copied.")} disabled={busy !== null} aria-label="Copy share link">
              <IconSwap name={done === "share" ? "check" : "link"} names={["link", "check"]} /> Share
            </Button>
          </>
        )}
      </div>
    </section>
  );
});
