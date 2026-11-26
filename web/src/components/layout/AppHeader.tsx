"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu } from "@/components/ui/Menu";
import { SettingsMenu } from "@/components/PrefsToggles";
import { CommandPalette } from "./CommandPalette";
import { AsOfLine } from "./AsOfLine";
import { ShortcutsHelp } from "./ShortcutsHelp";

const NAV = [
  { href: "/", label: "Screener" },
  { href: "/presets", label: "Presets" },
  { href: "/metrics", label: "Metrics" },
  { href: "/about", label: "About" },
];

/** The forest band: wordmark, navigation (inactive items soft), and settings. On phones the nav
 * folds into a menu so the band is one row (docs/ui-spec.md §2). */
export function AppHeader() {
  const path = usePathname();
  const router = useRouter();
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <header className="sticky top-banner z-20">
      <div className="flex items-center gap-x-6 bg-forest px-4 py-2">
        <Link href="/" className="text-section font-semibold text-on-forest">
          Glint
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => {
            const active = isActive(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-control border-b-2 px-2 py-1 text-label transition-colors duration-150 ease-out ${
                  active ? "border-on-forest text-on-forest" : "border-transparent text-sand-soft hover:text-on-forest"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <CommandPalette />
          <SettingsMenu />
          <div className="md:hidden">
            <Menu label="Menu" variant="band" items={NAV.map((n) => ({
                id: n.href,
                label: isActive(n.href) ? (
                  <span className="font-semibold">
                    {n.label}
                    <span className="sr-only">, current page</span>
                  </span>
                ) : (
                  n.label
                ),
                onSelect: () => router.push(n.href),
              }))} />
          </div>
          <ShortcutsHelp />
        </div>
      </div>
      <div className="border-b border-line bg-sand px-4 py-1">
        <AsOfLine />
      </div>
    </header>
  );
}

export function AppFooter() {
  return (
    <footer className="border-t border-line px-4 py-4 text-meta text-muted">
      Educational tool. Not investment advice. Fundamentals come from SEC XBRL filings; prices are a labelled second tier.{" "}
      <Link href="/about" className="text-ink-soft underline underline-offset-2">
        How Glint works
      </Link>
    </footer>
  );
}
