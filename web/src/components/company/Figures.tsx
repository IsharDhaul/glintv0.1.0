"use client";

import { Icon } from "@/components/ui/Icon";
import { MetricValue } from "@/components/ui/MetricValue";
import { NullValue } from "@/components/ui/NullValue";
import type { components } from "@/lib/api/types";
import { formatCount, formatPrice } from "@/lib/format";
import { screenCheck } from "@/lib/screen/check";
import { isGroup, type Condition, type Group, type MetricDefinition, type Screen } from "@/lib/screen/types";

type CompanyData = components["schemas"]["CompanyResponse"];

/** Price and market cap as the facts you scan for, then the screen check in one line. */
export function Figures({ data, defs, screen }: { data: CompanyData; defs: Map<string, MetricDefinition>; screen: Screen | null }) {
  const price = data.metrics.price;
  const cap = data.metrics.market_cap;
  const check = screen && data.why_passed ? screenCheck(screen, data.why_passed) : null;
  const name = (n: Condition | Group): string =>
    isGroup(n) ? [...new Set((n.children ?? []).map(name))].join(" or ") : (defs.get(n.metric)?.name ?? n.metric);
  return (
    <div className="space-y-1.5">
      <dl className="flex gap-6">
        <div>
          <dt className="text-meta text-muted">Price</dt>
          <dd className="num text-figure font-semibold text-ink">
            {typeof price?.value === "number" ? formatPrice(price.value) : <NullValue note={price?.note} fallbackReason="No price in this build." />}
          </dd>
        </div>
        <div>
          <dt className="text-meta text-muted">Market cap</dt>
          <dd className="num text-figure font-semibold text-ink">
            <MetricValue def={defs.get("market_cap") ?? { id: "market_cap", unit: "usd" }} value={cap?.value} note={cap?.note} />
          </dd>
        </div>
      </dl>
      {check && check.filters.length > 0 && (
        <p className="text-label">
          {!check.inUniverse ? (
            <span className="text-ink-soft">Outside this screen&apos;s universe.</span>
          ) : check.failed.length === 0 ? (
            <span className="text-forest">
              <Icon name="check" weight={600} className="mr-1" />
              Passes all {formatCount(check.filters.length)}
            </span>
          ) : (
            <>
              <span className="text-ink">
                Passes {formatCount(check.passedCount)} of {formatCount(check.filters.length)}.
              </span>{" "}
              <span className="text-neg">
                <Icon name="cross" weight={600} className="mr-0.5" />
                Fails {check.failed.map((f) => name(f.node)).join(", ")}.
              </span>
            </>
          )}
        </p>
      )}
    </div>
  );
}
