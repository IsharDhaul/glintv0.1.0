import { FadeScroller } from "@/components/ui/FadeScroller";
import Link from "next/link";
import type { ReactNode } from "react";
import { type Block, CLOSING, INTRO, METHODOLOGY, SECTOR_OVERRIDES } from "@/content/methodology";

export const metadata = { title: "About · Glint" };

// Renders web/src/content/methodology.ts (WT-10). All copy lives there; this file holds none.
export default function Page() {
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-title font-semibold">About Glint</h1>
        <p className="text-label text-muted">
          <Inline text={INTRO} />
        </p>
        <nav aria-label="Sections">
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-meta text-muted">
            {METHODOLOGY.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className="underline underline-offset-2 hover:text-ink-soft">
                  {s.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      {METHODOLOGY.map((s) => (
        <section key={s.id} className="space-y-2 text-label" aria-labelledby={s.id}>
          <h2 id={s.id} className="scroll-mt-16 text-section font-semibold text-ink-soft">
            {s.title}
          </h2>
          {s.blocks.map((b, i) => (
            <BlockView key={i} block={b} />
          ))}
          {s.id === "sectors" && <Overrides />}
        </section>
      ))}

      <p className="border-t border-line pt-4 text-label">
        <Inline text={CLOSING} />
      </p>
    </main>
  );
}

function Overrides() {
  if (SECTOR_OVERRIDES.length === 0) return <p className="text-muted">There are no manual sector overrides at the moment.</p>;
  return (
    <ul className="list-disc space-y-1 pl-5">
      {SECTOR_OVERRIDES.map((o) => (
        <li key={o.ticker}>
          <span className="num font-semibold text-forest">{o.ticker}</span>: {o.sector ?? o.kind}. {o.reason}
        </li>
      ))}
    </ul>
  );
}

function BlockView({ block }: { block: Block }) {
  if (block.kind === "p") {
    return (
      <p>
        <Inline text={block.text} />
      </p>
    );
  }
  if (block.kind === "ul") {
    return (
      <div className="space-y-1">
        {block.lead && (
          <p>
            <Inline text={block.lead} />
          </p>
        )}
        <ul className="list-disc space-y-1 pl-5">
          {block.items.map((item, i) => (
            <li key={i}>
              <Inline text={item} />
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <FadeScroller>
        <table className="w-full border-collapse text-meta">
          <thead>
            <tr className="border-b border-line-strong text-left text-muted">
              {block.head.map((h) => (
                <th key={h} scope="col" className="px-2 py-1 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, r) => (
              <tr key={r} className="border-b border-line">
                {row.map((cell, c) =>
                  c === 0 ? (
                    <th key={c} scope="row" className="px-2 py-1 text-left font-normal">
                      <Inline text={cell} />
                    </th>
                  ) : (
                    <td key={c} className="px-2 py-1">
                      <Inline text={cell} />
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </FadeScroller>
      {block.foot && (
        <p className="text-meta text-muted">
          <Inline text={block.foot} />
        </p>
      )}
    </div>
  );
}

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

/** Renders the copy's inline markup: **bold**, `code`, [text](/path). */
function Inline({ text }: { text: string }) {
  const parts: ReactNode[] = text.split(TOKEN).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="text-ink-soft">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="font-code text-meta">
          {part.slice(1, -1)}
        </code>
      );
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link?.[1] && link[2]) {
      return (
        <Link key={i} href={link[2]} className="text-forest underline underline-offset-2">
          {link[1]}
        </Link>
      );
    }
    return part;
  });
  return <>{parts}</>;
}
