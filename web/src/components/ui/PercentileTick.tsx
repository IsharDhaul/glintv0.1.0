import { formatPercentile } from "@/lib/format";
import { Tooltip } from "./Tooltip";

/** A sector-percentile tick: a short track with a forest dot, "p87", and the direction in words. */
export function PercentileTick({ p, said }: { p: number; said: string }) {
  return (
    <Tooltip tip={said}>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="relative inline-block h-0.5 w-12 rounded-full bg-line-strong/50">
          <span className="absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-forest" style={{ left: `${p * 100}%` }} />
        </span>
        <span className="num text-meta text-muted">
          {formatPercentile(p)}
          <span className="sr-only">, {said}</span>
        </span>
      </span>
    </Tooltip>
  );
}
