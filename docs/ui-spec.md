# Glint UI spec: developer handoff

Phase 2 of `docs/glint-ui-upgrade.md`. It implements the **Visual standard** in that brief and the direction in `docs/design-direction.md`. Where this spec and the standard disagree, the standard wins, and this file gets fixed.

How to use it:
- Every visual value comes from a token in §1. Components never contain a raw hex, px size or duration.
- Every number goes through `web/src/lib/format.ts` (§3). `no-stray-formatting.test.ts` already enforces this, and §1.6 adds a matching test for raw colours.
- Each component in §4 names the existing file it replaces or extends. Nothing is rebuilt in parallel.

---

## 1. Design tokens

### 1.1 Where they live

`web/src/app/globals.css` stays the single source: CSS custom properties on `:root`, exposed to Tailwind through `@theme inline`. There's only one theme now.

Phase 4.1 deletes:
- the `[data-theme="dark"]` and `[data-theme="light"]` blocks;
- the `dark` custom variant;
- `THEME_KEY` and the theme half of `PREFS_SCRIPT` in `lib/prefs.ts`;
- the theme toggle in `PrefsToggles.tsx`.

Density stays.

### 1.2 Colour

```css
:root {
  color-scheme: light;
  /* surfaces */
  --sand: #e8dcc4;        /* page ground */
  --paper: #f6f1e7;       /* tables, drawer, panels */
  --dune: #ddcfb2;        /* table header, hover, pressed */
  /* text tiers */
  --ink: #16261c;         /* crisp: ticker, price, market cap, screened values, sieve counts */
  --ink-soft: #344238;    /* soft: labels, prose, 10-K facts, values outside the screen */
  --muted: #4f5345;       /* quiet: meta, units, medians, sources, — and n/m */
  /* brand and interaction */
  --forest: #1f3d2b;      /* brand, "kept", primary actions, tickers */
  --on-forest: #f6f1e7;   /* text on forest (paper) */
  --sand-soft: #b6b49e;   /* inactive nav on the forest band */
  --purple: #8b5cf6;      /* the user's hand: focus, selection, handle, changed count. Fills only */
  --purple-ink: #5b2ed1;  /* purple as text (command palette active item) */
  /* data */
  --pos: #17508e;         /* up, with + and ▲ */
  --neg: #9c3118;         /* down, with − and ▼ */
  --caution: #734600;     /* stale, flags, warnings */
  --nodata: #7d735c;      /* no-data bars, always hatched */
  /* lines */
  --line: #d2c4a6;        /* dividers */
  --line-strong: #7a6d50; /* control borders, ≥ 3:1 on every surface */
  /* banner (mock mode) */
  --banner: #d9a441;
  --on-banner: #16261c;
}
```

`@theme inline` maps each one to a colour utility: `bg-sand`, `bg-paper`, `bg-dune`, `text-ink`, `text-ink-soft`, `text-muted`, `bg-forest`, `text-on-forest`, `text-sand-soft`, `ring-purple`, `bg-purple`, `text-purple-ink`, `text-pos`, `text-neg`, `text-caution`, `bg-nodata`, `border-line`, `border-line-strong`, `bg-banner`, `text-on-banner`.

The old names (`bg`, `surface`, `surface-2`, `text`, `accent`, `accent-2`, `warn`, `on-accent`, `on-warn`) are removed. Every use gets renamed in the same commit:

| Old | New |
|---|---|
| `bg` | `sand` |
| `surface` | `paper` |
| `surface-2` | `dune` |
| `text` | `ink-soft`, or `ink` where crisp |
| `accent` | `forest` (brand) or `purple` (focus/selection), decided case by case |
| `accent-2` | `forest` for links (underlined), `nodata`/`line` for neutral bins |
| `warn` | `caution` |

Shared patterns, defined once in `globals.css`:
- **Hatch:** `--hatch: repeating-linear-gradient(135deg, var(--nodata) 0 2px, transparent 2px 5px);` Used for no-data bars and the banner. On the banner it's drawn with `color-mix(in oklab, var(--ink) 12%, transparent)` over `--banner`.
- **Tints:** token plus alpha only, for example `bg-dune/50` for row hover and `bg-purple/10` for the command palette's active row. There are no new hexes.

### 1.3 Type

```css
:root {
  --font-words: "Atkinson Hyperlegible Next", "Atkinson Hyperlegible", ui-sans-serif, system-ui, sans-serif;
  --font-numbers: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  --font-code: "IBM Plex Mono", ui-monospace, monospace;
}
```

- **Fonts are loaded in `app/layout.tsx`** via `@fontsource` CSS imports. Atkinson Next in weights 400/500/600, Plex Sans in 400/500/600, Plex Mono in 400. No network at build or run time.
  - The `geist` dependency and its `variable` classes are removed.
  - If `@fontsource/atkinson-hyperlegible-next` doesn't exist, use `@fontsource/atkinson-hyperlegible` (400/700, with 700 standing in for 600) and log the swap in `docs/ui-decisions.md`.
- **`body`** uses `--font-words`, weight 400, colour `--ink-soft`, on `--sand`.
- **`.num`, `table`, `input[inputmode="decimal"]`** use `--font-numbers` with `font-variant-numeric: tabular-nums`.

The scale lives as Tailwind theme keys; components use these names, never raw sizes:

| Token class | Size / line height | Family | Weight | Use |
|---|---|---|---|---|
| `text-title` | 24/32 | words | 600 | Page title (company name, screen name) |
| `text-section` | 16/24 | words | 600 | Section titles |
| `text-prose` | 15/24 | words | 400 | Prose, flag questions, empty states, tooltips; wrap in `max-w-prose` (70ch) |
| `text-label` | 13/20 | words | 400 | Labels, navigation, metric names, buttons |
| `text-cell` | 13/20 | numbers | 400 / 500 | Table body; 500 and `text-ink` on screened columns |
| `text-head` | 12/16 | words | 500 | Table headers, sentence case, no tracking |
| `text-meta` | 12/16 | words | 400 | As-of lines, units, medians |
| `text-figure` | 20/28 | numbers | 600 | Price, market cap, sieve counts, headline values |
| `text-ticker` | 13/20 | numbers | 600 | Ticker in tables and lists (`text-forest`) |
| `text-ticker-lg` | 24/32 | numbers | 600 | Ticker in page and drawer headers |
| `text-code` | 12/16 | code | 400 | Formulas, XBRL tags, accessions, build ids |

Rules:
- **No weight below 400.**
- **No `uppercase`, no `tracking-*` utilities** anywhere in `web/src`. The §1.6 test checks this.
- **Italics** only for a single term being defined.

### 1.4 Space, radius, elevation, layers

```css
:root {
  /* 4px base */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-6: 24px; --space-8: 32px;
  /* density (unchanged mechanism: data-density on <html>) */
  --row-h: 32px; --ctl-h: 28px; --cell-x: 8px;        /* compact */
  /* [data-density="comfortable"]: --row-h: 40px; --ctl-h: 36px; --cell-x: 12px; */
  --touch: 44px;                                        /* minimum target under 768px */
  /* radius by hierarchy */
  --radius-control: 2px;  /* inputs, buttons, focus outlines */
  --radius-panel: 4px;    /* panels, table frame, popovers, tooltips */
  --radius-sheet: 8px;    /* drawer leading corners, bottom sheet, command palette */
  --radius-pill: 999px;   /* removable universe rules only */
  /* the one elevation */
  --shadow-overlay: 0 8px 24px rgb(22 38 28 / 0.18);
  /* layers */
  --z-sticky: 10; --z-drawer: 30; --z-sheet: 40; --z-palette: 50; --z-banner: 60;
  /* focus */
  --focus-ring: 0 0 0 2px var(--paper), 0 0 0 4px var(--purple);
}
```

- Focus is `:focus-visible { outline: none; box-shadow: var(--focus-ring); border-radius: var(--radius-control); }`. The paper gap keeps purple at 3:1 next to forest.
- Panels never get a shadow.

### 1.5 Motion

```css
:root {
  --ease-out: cubic-bezier(0.2, 0.8, 0.2, 1);
  --dur-instant: 0ms;     /* threshold handle follows the pointer */
  --dur-quick: 120ms;     /* hover, pressed */
  --dur-sheet: 160ms;     /* drawer, sheets, palette */
  --dur-tick: 200ms;      /* count ticks */
  --dur-sieve-fill: 400ms;/* the one first-load moment, total across all trays */
  --dur-changed: 1500ms;  /* purple underline on a count the user's edit changed */
}
@media (prefers-reduced-motion: reduce) { /* existing global rule stays: no animation, no transition */ }
```

- The gold `.glint-new` shimmer is removed.
- Rows that entered the results because of the user's edit get a 3px `purple` left bar for `--dur-changed`. With reduced motion, the bar shows statically for the same time.

### 1.6 Enforcement

Add `web/src/lib/no-raw-style.test.ts`, alongside `no-stray-formatting.test.ts`. It scans `web/src/**/*.tsx` and fails on:
- `#` hex literals;
- `rgb(`;
- `text-[` or `px-[` style arbitrary values;
- `uppercase` or `tracking-`;
- `font-mono` outside the components that render formulas, tags or accessions (an allow-list).

`globals.css` is exempt.

---

## 2. Layout and responsive behaviour

| | Desktop > 1024px | Tablet 768–1024px | Mobile < 768px |
|---|---|---|---|
| Header band | Forest, 48px: wordmark, nav, search on the right, settings menu (density) | Same; nav collapses to a menu button | 48px: wordmark, search icon (opens the palette full-screen), menu |
| Screen bar | Screen name, Universe control, Share, Export, as-of line | Same, wraps to two lines | Screen name; Share and Export in the menu |
| Filters | Left rail 280px, always visible | Rail hidden; a "Filters (5)" button opens it as a left sheet, 320px | Sticky summary bar ("5 filters, 139 results" + "Filters"); filters open in a bottom sheet at 90vh |
| Sieve | Full row of trays above the table | Full row, scrolls horizontally with edge shadows | One-line summary under the summary bar; the full sieve sits at the top of the filters sheet |
| Table | All chosen columns; sticky header and ticker column | Same, with horizontal scroll and shadow | Ticker, short name, score (ranked screens), one chosen metric; 44px rows |
| Near misses | Below the table | Below the table | Collapsed section below the table |
| Drawer | Right, 480px; the ticker column stays visible | Right, 60% width, ticker column visible | Full-screen sheet, opened by tap or swipe-left on a row |
| Company page | 12-column grid; metric groups in CSS columns (3) | 2 columns | 1 column |

Alignment:
- Text is left-aligned. Numbers are right-aligned and decimal-aligned.
- Nothing is centred except empty states, and those are centred inside their region.
- Maximum content width is 1440px; the sand ground shows beyond it.

---

## 3. Number formatting rules (all in `web/src/lib/format.ts`)

Every rule below is a named function in `format.ts` with unit tests in `format.test.ts`. Components never call `toFixed` or `Intl` directly.

| Kind | Function | Context | Rule | Examples |
|---|---|---|---|---|
| Percent | `formatFrac` | Tables, values | 1 dp, typographic minus | `15.2%`, `−3.0%` |
| Percent threshold | `formatThreshold(unit, v)` | Filter labels, sieve labels, inputs | Drop trailing zeros | `≥ 40%`, `≥ 15.5%`, `≤ 2x`, `≥ $1M/day` |
| Difference | `formatPp` | Changes, vs-median | Signed, 1 dp, `pp` | `+2.3 pp`, `−0.4 pp` |
| Gap | `formatGap` (exists) | Near misses | Unsigned, in metric units | `7.5 pp short`, `0.4x over` |
| Multiple | `formatMultiple` | Tables | 1 dp + `x` | `14.2x` |
| Currency | `formatUsd` | Tables, headers | Compact. Below 10: 2 significant decimals (`$6.4B`, `$1.2M`); 10–99.9: 1 dp (`$22.1B`); ≥ 100: 0 dp (`$312M`). Trailing zeros dropped (`$6B`, not `$6.0B`). Below $1,000: 2 dp | `$6.4B`, `$221B`, `$9.38` |
| Price | `formatPrice` (new) | Price only | 2 dp always | `$512.40` |
| Count | `formatCount` (exists) | Companies, flags | Integer with grouping | `2,777`, `1` (never `1.00`) |
| Score | `formatScore` (exists) | Rank score | 2 dp; fixed-scale scores as `7/9` | `0.91`, `7/9` |
| Days | `formatDays` (exists) | Days | Integer + ` d` | `47 d` |
| Percentile | `formatPercentile(p)` (new) | Compact slots | `p` + integer 0–100 | `p87` |
| Percentile, said | `describePercentile(p, def, scope)` (new) | Tooltips, screen check | Direction-aware, from the metric's `better` | `better than 87% of Technology` (higher better, p87); `better than 13% of Technology` (lower better, p87); `higher than 87% of Technology` (neutral) |
| Missing | `NullValue` | Anywhere | `—`, tooltip with the reason label + message | |
| Not meaningful | `NullValue` | Anywhere | `n/m`, tooltip | |

Inputs:
- A threshold input shows the same number as its label, with the unit outside the field: `[15] %`. It never shows `15 %` inside the input.
- Parsing stays in `lib/units.ts`.

The table header's tooltip, on every null-capable column, says: "— means the filings don't have a value. n/m means the value isn't meaningful here (for example, a ratio with a negative denominator)."

---

## 4. Component inventory

Shared state definitions, used by every component below:

| State | Treatment |
|---|---|
| **default** | As specified |
| **hover** | `bg-dune/50` on rows and tray buttons; `border-ink-soft` on controls; `--dur-quick` |
| **focus-visible** | `--focus-ring` |
| **active** | `bg-dune` (pressed) |
| **disabled** | `text-muted`, `cursor-not-allowed`, no hover; reason in a tooltip |
| **loading** | Skeleton blocks in `bg-dune/60` at the final size (no layout shift), `aria-busy="true"` on the region |
| **empty** | One `text-prose` sentence saying what happened and one action |
| **error** | `text-prose` in `ink-soft`, with a 2px `neg` rule on the left: what failed, what to do, a Retry button |
| **no data** | `—` via `NullValue`; in bars, `nodata` + hatch |
| **not meaningful** | `n/m` via `NullValue`; in bars, excluded and counted in the tooltip |

### 4.1 FilterRow

Replaces the filter cards in `components/screener/FilterPanel.tsx` and `ConditionEditor.tsx`.

```ts
type FilterRowProps = {
  path: NodePath;                       // lib/screen/filters.ts
  condition: Condition;
  def: MetricDefinition | undefined;
  kept: number | null;                  // companies left after this step (funnel)
  removed: number | null;
  removedMissing: number | null;
  binding: boolean;
  expanded: boolean;
  distribution: DistributionResponse | undefined;
  onChange(c: Condition): void;         // threshold, operator, missing policy
  onRemove(): void;
  onToggleExpanded(): void;
};
```

**Collapsed:** one line, 32px (44px under 768px).

`ROIC   [≥]   [15] %          1,744   ✕`

- Metric name: `text-label ink-soft`; click to change the metric (opens the metric picker).
- **Operator:** a 2px-radius button. Click flips ≥ ↔ ≤ (or > ↔ <). Long-press or the context menu offers between, percentile and vs-median.
- **Threshold:** an inline numeric input in `text-cell`. Enter or blur commits, Esc reverts.
- **Kept count:** `text-cell`, right-aligned. On the binding filter it's `ink` 600 with "removes the most" in `text-meta` beside it.
- **✕** appears on row hover or focus, and is always visible on touch.

**Expanded:** the histogram (§4.2), the "Missing values pass" toggle with its effect ("+2,777"), and the scope selector for percentile filters.

**OR groups:** child rows indented 16px under a `text-meta` line, "Any of:".

| State | Treatment |
|---|---|
| hover | Row `bg-dune/50`; ✕ visible |
| focus-visible | Ring on the focused control; the row shows ✕ |
| disabled | Not used |
| loading | Kept count shows a 24px skeleton; the previous value stays dimmed (`text-muted`) while the request is in flight |
| empty (no filters) | Rail says "Add a filter to start narrowing the universe." plus an `Add filter` primary button |
| error (invalid value) | The input gets a `neg` border; `text-meta neg` below says "Enter a number between 0 and 100." |
| incomplete | Threshold empty: the count shows "—" with the tooltip "Not applied until it has a value." |
| no data | Kept count `—` |

ARIA:
- The row is `role="group"` with the label "Filter: ROIC at least 15%".
- The operator button has `aria-label="Operator: at least. Activate to switch to at most"`.

### 4.2 Histogram

Rewrites `components/ui/Histogram.tsx`.

```ts
type HistogramProps = {
  bins: HistogramBin[];            // API: 30 bins over p1–p99; the first and last absorb the tails
  nullCount: number;               // DistributionResponse.null_count
  threshold: number | [number, number] | null;
  cmp: Comparator;
  unit: Unit;
  onThreshold?(v: number): void;   // drag / keys; absent = read-only
  label: string;
};
```

- **Bins are drawn at equal widths by index, not on a linear value axis.** This is the fix for the collapsed histograms: the end bins hold the tails, which can be −17,919%. Only the interior edges sit on a value scale; the axis labels show `p1` and `p99` values.
- **Under/overflow:** the first and last bins are drawn 6px apart from the rest, with labels "≤ −45%" and "≥ 210%" (their inner edges). Phase 3 decides whether the API sends explicit underflow and overflow counts; until then, the end bins play that role.
- **Colour:** bins on the kept side are `forest`; the rest are `line-strong` at 40%. A bin the threshold splits is drawn in two parts, proportionally.
- **No data:** a separate bar to the right, past a 12px gap, `nodata` + hatch, labelled "No data: 2,777".
- **Handle:** a 2px `purple` line with a 12px circular grip on top, ringed in `paper`.
  - Drag moves it; it snaps to bin edges while dragging and to the typed value on input.
  - ←/→ move one bin, Shift+←/→ move ten. Home and End go to the extremes.
  - The live count updates while dragging (Phase 3 decides how).

| State | Treatment |
|---|---|
| default | Bars at 48px tall, axis labels `text-meta` |
| hover | Bin under the pointer gets a `line-strong` outline; tooltip "12.0% to 14.5%: 312 companies" |
| focus-visible | The handle gets `--focus-ring` |
| active (dragging) | Handle grip 14px, cursor `ew-resize` |
| disabled (read-only) | No handle; markers only |
| loading | A 48px skeleton |
| empty (every value null) | Only the no-data bar, plus "No company has a value for this metric." |
| error | "Couldn't load the distribution." + Retry |
| n/m | n/m companies aren't plotted; the tooltip on the no-data bar splits "2,700 missing, 77 not meaningful" when the API reports both |

ARIA:
- `role="slider"` on the handle, with `aria-valuemin`, `aria-valuemax`, `aria-valuenow`, and `aria-valuetext="15%, 1,744 companies kept"`.
- The figure has `role="img"` and an `aria-label` summary.

### 4.3 SieveStage

Splits `components/ui/SieveBar.tsx` into `Sieve` (the row) and `SieveStage` (one tray).

```ts
type SieveStageProps = {
  step: FunnelStep;            // remaining, removed, removed_missing, binding
  universe: number;            // funnel[0].remaining: every tray is scaled to this
  previous: number;            // previous stage's remaining
  label: string;               // stepLabel() from lib/screen/funnel.ts
  changed: boolean;            // count changed because of the user's last edit
  onOpen(step: FunnelStep): void;  // shows the removed companies
};
```

- **Layout:** the label (`text-label ink-soft`, truncates with a tooltip) sits over the count (`text-figure ink`), over a 10px bar.
- **The bar spans the full tray width, which stands for the universe.** Left to right:
  - kept, `forest`;
  - failed (`removed − removed_missing`), `line`;
  - no data (`removed_missing`), `nodata` + hatch;
  - the remainder, already gone in earlier stages, transparent with a `line` outline.

  Widths are linear, not √: the eye compares against one frame. A non-zero segment gets at least 2px.
- **Binding stage:** the text "removes the most" in `text-meta ink` under the bar. When `removed_missing / removed > 0.5`, it also says "2,777 have no ROIC". The tooltip explains: "Of all filters, this one removes the most companies. Loosening it, or letting missing values pass, changes the result most."
- **Changed:** the count gets a 2px `purple` underline for `--dur-changed`, and the number ticks (`--dur-tick`).
- **Click or Enter** opens the stage's removed list (Phase 4.4) inside the sieve panel, with "Include these".

| State | Treatment |
|---|---|
| hover / focus-visible | Tray `bg-dune/50` / ring; the tooltip shows exact kept / failed / no data |
| active | `bg-dune` |
| loading | Bar and count keep the previous values at 60% opacity; skeleton on first load only |
| empty (0 kept) | Count `0` in `ink`, bar all failed/no data; the final stage gets no special mark |
| error | The whole sieve is replaced by the error block |
| no data stage | A stage removing only missing values shows an all-hatch segment |

ARIA:
- The `Sieve` is an `ol` with `aria-label="Sieve"`; each stage is a `button`.
- Its label reads: "ROIC at least 15%: 1,744 kept, 891 failed, 2,777 had no data. Removes the most."

### 4.4 ResultsTable

Extends `components/screener/ResultsTable.tsx` (TanStack Table + Virtual, already virtualised).

```ts
type ResultsTableProps = {
  rows: ResultRow[]; total: number; screen: Screen;
  columns: string[];                        // ticker first
  metrics: Map<string, MetricDefinition>;
  screened: ReadonlySet<string>;            // metric ids in the active screen: crisp columns
  selected: string | null;                  // ticker
  pinned: string[];                         // compare tray, max 3
  entered: ReadonlySet<string>;             // tickers that entered because of the last edit
  onOpen(ticker: string, how: "drawer" | "page"): void;
  onSort(column: string, additive: boolean): void;   // Shift-click adds a secondary sort
  onPin(ticker: string): void;
  pending: boolean;
};
```

- **Frame:** `paper`, `--radius-panel`.
  - The header is `dune`, sticky, `text-head muted`.
  - The ticker column is sticky. When the table scrolls horizontally, a shadow appears at the right edge of the ticker column. That uses the one elevation token, the only allowed exception.
- **Rows:** `--row-h`, `line` dividers, no zebra stripes.
- **Cells:**
  - Ticker: `text-ticker forest`.
  - Name: `text-label ink-soft`, display-normalised: title case, with trailing Inc., Corp., Ltd, plc, Holdings, Co dropped. The full legal name lives in the drawer.
  - Sector: `ink-soft`.
  - Screened metric columns and the Score: `text-cell` 500 `ink`.
  - Other numbers: `text-cell` 400 `ink-soft`.
- **Status slot:** a fixed 16px slot left of each number, for ⓘ (info note) or a `caution` dot for stale data. Decimals stay aligned.
- **Score column** on ranked screens, first after the name. Its header tooltip explains the rank method.
- **Sort:** the header shows ▲/▼ plus `aria-sort`. A secondary sort shows a small "2".
- **Column picker:** a searchable popover. The screen's metrics are on by default.

Keyboard:
- j/k or ↑/↓ move the selection; Enter opens the drawer; o opens the full page; x pins.
- Home and End jump to the first and last row; PageUp and PageDown move by a page.

| State | Treatment |
|---|---|
| hover | Row `bg-dune/50` |
| selected | Row `bg-dune`, 3px `purple` bar on the left edge |
| focus-visible | Row ring (inset) |
| pinned | Small forest ◆ in the status slot of the ticker cell, label "Pinned for compare" |
| entered | Purple left bar for `--dur-changed` |
| loading (first) | 12 skeleton rows |
| pending (refetch) | Rows stay, 60% opacity, `aria-busy`; the count reads "Updating…" |
| empty | See §5 "0 results" |
| error | Error block in place of the rows; the previous result is never shown as current |
| no data / n/m | `NullValue` |

ARIA:
- `role="grid"` with `aria-rowcount={total}` and `aria-colcount`.
- Rows are `role="row"` with `aria-rowindex` and `aria-selected`; the ticker cell is a `rowheader`.

### 4.5 DrawerHeader

Replaces the title and subtitle props of `components/ui/Drawer.tsx` as used by `CompanyDrawer.tsx`.

```ts
type DrawerHeaderProps = {
  company: CompanyHeader;
  price: number | null; marketCap: number | null;
  asOfPrices: string | null;
  check: ScreenCheck | null;      // lib/screen/check.ts
  position: { index: number; total: number } | null;  // "12 of 139" while flicking with j/k
  onPrev(): void; onNext(): void; onClose(): void; onOpenPage(): void; onPin(): void;
};
```

Layout:
- **Line 1:** ticker (`text-ticker-lg forest`) and display name (`text-section ink`). On the right: Pin, Open page, ✕.
- **Line 2:** price (`text-figure ink`, `formatPrice`) and market cap (`text-figure ink`), labels in `text-meta muted`.
- **Line 3:** "Technology, Nasdaq" (`text-label ink-soft`).
- **Line 4:** the ScreenCheck summary (§4.6).
- **Footer strip:** "12 of 139" plus ↑/↓ buttons.

The full legal name appears in Company details, not here.

| State | Treatment |
|---|---|
| loading | Ticker shown immediately (from the row); the rest as skeletons |
| error | Ticker kept; error block below |
| no data | Price `—` with a reason tooltip ("No price in this build") |
| n/m | Market cap `n/m` for foreign filers (FOREIGN_PRICE_BASIS), with the tooltip |

ARIA:
- The drawer is `role="dialog"`, labelled by the ticker and name.
- Focus moves to the dialog on open and returns to the row on close.
- j/k inside the drawer move to the next or previous result and announce "ADBE, Adobe, 12 of 139" in a polite live region.

### 4.6 ScreenCheck

Extends `ScreenCheckSection` in `components/company/CompanyView.tsx`, using `screenCheck()` from `lib/screen/check.ts`.

```ts
type ScreenCheckProps = { screen: Screen | null; outcomes: FilterOutcome[] | null; defs: Map<string, MetricDefinition>; variant: "summary" | "full" };
```

- **summary** (drawer header, company header): one line.
  - "Passes all 5" (`ink`, with a `forest` ✓).
  - "Passes 3 of 5. Fails ROIC, FCF margin." (`ink`; the failure names in `neg`, with ✗).
- **full:** the summary plus one row per filter: ✓/✗ + "Passed"/"Failed", the filter label, the value (crisp), and the percentile tick (§4.7) with `describePercentile` in its tooltip.

| State | Treatment |
|---|---|
| no screen context | Not rendered. The company page says nothing about screens. |
| outside the universe | "Outside this screen's universe" + the rule that excludes it ("Market cap below $300M") |
| screen with no complete filters | "Screen check: this screen has no filters yet." |
| loading | One skeleton line |
| no data | A filter whose value is missing: ✗ Failed, value `—` (or ✓ when missing values pass, with "missing values pass" in `text-meta`) |

### 4.7 MetricGroup

Replaces `MetricsByCategory` in `CompanyView.tsx`.

```ts
type MetricGroupProps = {
  category: Category; metrics: MetricDefinition[]; cells: Record<string, MetricValue>;
  medians: Record<string, number | null>;      // sector medians (Phase 3 contract)
  percentiles: Record<string, number | null>;  // sector percentiles
  screened: ReadonlySet<string>;
  collapsed: boolean; onToggle(): void;        // remembered in localStorage per category
};
```

- **Layout:** groups flow in CSS columns (`columns-3` desktop, `columns-2` tablet, `columns-1` mobile), with `break-inside: avoid`, so there are no holes.
- **Group heading:** `text-section ink-soft`, a toggle button with ▸/▾ and the metric count in `text-meta`. No box around the group; a `line` divider between rows.
- **Metric row:**
  - name (`text-label ink-soft`, tooltip: plain-language definition, basis, unit, source tier);
  - value, right-aligned: `text-cell`, `ink` 500 if screened, else `ink-soft` 400;
  - sector median (`text-meta muted`, "median 12.1%");
  - percentile tick (60×8px): a `line-strong` track with a `forest` dot, tooltip from `describePercentile`.
- **Screened metrics** get a 2px `forest` rule on the left.
- **Price-dependent metrics** get one small `muted` marker (`$`) in the status slot. A single legend line under the groups explains it: "$ uses the latest market price."

| State | Treatment |
|---|---|
| collapsed | Heading only |
| loading | Heading + 4 skeleton rows |
| no data | Value `—`; no tick |
| n/m | Value `n/m`; no tick |
| no median (small sector) | "median —" with the SMALL_PEER_GROUP tooltip |

### 4.8 Sparkline

Rewrites `components/company/Sparklines.tsx`. It stays Recharts, lazy-loaded, and never appears in table rows.

```ts
type SparklineProps = { def: MetricDefinition; points: HistoryPoint[]; basis: "fy" | "ttm"; height?: number };
```

- **One chart per metric, with FY and TTM on a shared y-axis.** FY is a `forest` line with dots; TTM is an `ink-soft` 1.5px line. A legend line reads "FY ● TTM —".
- **Zero baseline** (`line-strong`, dashed) whenever the domain crosses 0, and always for margins.
- **Labels:** the start value and date at the left, the end value and date at the right (`text-meta`, values in `numbers`). The end TTM value equals the headline metric; Phase 0 invariant tests guard this.
- **Gaps:** a null point breaks the line, and the gap gets a hatched `nodata` band with the tooltip "No value for FY2019 in this build."
- **Crosshair:** on hover or focus, a vertical `line-strong` line, with a tooltip "FY2023: $4.31B". Keyboard ←/→ move it.

| State | Treatment |
|---|---|
| loading | 64px skeleton |
| empty (< 2 points) | "Not enough history to draw." in `text-meta` |
| all null | "No history in this build." |
| error | "Couldn't load history." + Retry |

ARIA: `role="img"`, with an `aria-label` summary ("Revenue, TTM: $4.31B (Mar 2023) to $6.98B (Dec 2025), 12 points, 1 missing").

### 4.9 Chip

Narrows `components/ui/Chip.tsx`.

Chips are only for **removable or toggleable** things: universe rules inside the Universe popover, near-miss filter toggles, compare-tray tickers. Everything that was a non-interactive pill becomes plain text:
- `Badge`s for flag counts and coverage become plain `text-cell` numbers;
- tier and kind badges in the company facts become plain text.

```ts
type ChipProps = { children: ReactNode; pressed?: boolean; onToggle?(): void; onRemove?(): void; locked?: boolean; lockReason?: string };
```

- **Default:** `paper`, `line-strong` border, `--radius-pill`, `text-label ink-soft`, 24px tall (44px hit area under 768px).
- **pressed:** `bg-forest text-on-forest`.
- **locked:** a lock icon instead of ✕, `muted` text, and a tooltip with `lockReason` ("Glint only screens companies with XBRL financial statements.").

| State | Treatment |
|---|---|
| hover | Border `ink-soft` |
| focus-visible | Ring |
| active | `bg-dune` |
| disabled | `muted`, no hover |

### 4.10 CommandPalette (new: `components/layout/CommandPalette.tsx`)

```ts
type Command =
  | { kind: "company"; ticker: string; name: string; sector: Sector }
  | { kind: "preset"; id: string; name: string }
  | { kind: "add-filter"; metric: string; name: string }
  | { kind: "action"; id: "toggle-density" | "share" | "export" | "shortcuts"; label: string };
```

- **Opening:** `/` or ⌘K / Ctrl+K anywhere (not while typing in a field), or click the header search.
- **Layout:** a 560px-wide panel at 15vh, `paper`, `--radius-sheet`, `--shadow-overlay`. On mobile it's full screen.
- **Input:** `text-section`, placeholder "Search ticker or company, or type a command".
- **Results:** grouped as Companies (from `/api/search`, debounced 120ms), Presets, Filters, Actions. Matching is fuzzy on ticker and name; prefix matches rank first.
  - A row shows the ticker (`text-ticker forest`), name (`ink-soft`) and sector (`muted`).
  - The active row is `bg-purple/10` with `purple-ink` text and a `purple` left bar.
- **Keys:** ↑/↓ move, Enter opens the drawer (company) or runs the command, ⌘/Ctrl+Enter opens the full company page, Esc closes.

| State | Treatment |
|---|---|
| empty query | Recent companies (last 5, localStorage), then presets |
| loading | Company group shows "Searching…" (`muted`); other groups stay |
| no results | "No company or command matches "xyz"." |
| error | Company group shows "Search isn't available right now." Commands still work. |

ARIA:
- The input is `role="combobox"` with `aria-expanded`, `aria-controls` and `aria-activedescendant`.
- The list is a `listbox`, groups are `group`s with labels, rows are `option`s.

### 4.11 NearMissList

Rewrites `components/screener/NearMisses.tsx`.

```ts
type NearMissListProps = {
  items: NearMiss[]; metrics: Map<string, MetricDefinition>;
  labelFor(m: NearMiss): string;           // lib/screen/funnel.ts stepLabel
  onOpen(ticker: string): void;
  onRelax(m: NearMiss): void;              // sets that filter's threshold to the value
  relaxPreview(m: NearMiss): number | null;// result count if relaxed (Phase 3)
};
```

- **Row:**
  - ticker (`text-ticker forest`), display name (`ink-soft`);
  - "FCF margin 9.5%" with the value crisp;
  - the gap via `describeDistance` (`text-label caution`, e.g. "0.5 pp short");
  - an action button "Include" whose tooltip says "Lower FCF margin to 9.5%: 140 results".
- **Order:**
  - Within one filter, rows sort by gap in metric units.
  - Across filters, they keep the engine's relative order and are grouped under one `text-label` heading per filter ("Missed FCF margin ≥ 10%, 4 companies"). This keeps unlike units from being compared in one sorted list.
- **Toggle chips** filter by failed filter (Chip, pressed state).

| State | Treatment |
|---|---|
| hover | Row `bg-dune/50` |
| focus-visible | Ring on the row button |
| loading | 4 skeleton rows |
| empty | "No company missed by just one filter." |
| near misses off | "Near misses are off." + toggle |
| no data value | Value `—` with its reason; no gap; Include is hidden (missing values can't be fixed by a threshold); tooltip "Turn on 'Missing values pass' for this filter to include it." |
| n/m | Value `n/m`; Include hidden |

---

## 5. Edge cases

| Case | Behaviour |
|---|---|
| **0 results** | The table area shows the sieve's last tray emphasised and one sentence built from near misses: "Lowering FCF margin to 7.4% adds 1 company." Its button applies that. If there are no near misses: "No company passes all 5 filters. The filter that removes the most is ROIC (2,777 of its removals have no ROIC); try letting missing values pass." |
| **1 result** | The table shows one row; the count says "1 company". The drawer opens with the position strip hidden. |
| **5,000 results** | Virtualised, no 100-row cap (Phase 3 decides paging versus a columnar payload). The count reads "5,000 companies". Export says how many rows it will write. |
| **ROIC missing for 70% of the universe** | The binding tray says "2,777 have no ROIC". The FilterRow's missing toggle shows "+2,777". The histogram's no-data bar is drawn to scale, which makes it the longest bar. Advice never suggests loosening the threshold to recover missing values. |
| **Extreme outliers** | The histogram's end bins absorb the tails, with labels "≤ p1 value" and "≥ p99 value". Table values print as they are (`−17,919.0%`); the column never auto-scales. Sparkline domains are clipped to p5–p95 of the series, with a ▲/▼ marker at the edge for clipped points and the true value in the tooltip. |
| **Long company names** | Tables show the display name truncated with an ellipsis at the column width; the full display name is in the `title`/tooltip; the full legal name is in the drawer's Company details. The page title wraps to at most 2 lines. |
| **Company opened with no screen context** | No ScreenCheck. The screen's metrics block becomes "Key metrics" (market cap, revenue, operating margin, ROIC, FCF yield, net debt/EBITDA). No highlighted metrics. The back link reads "Back to the screener". |
| **Missing price** | Price and price-tier metrics show `—` with "No price in this build"; SEC-tier metrics are unaffected. |
| **Synthetic build** | The banner is always on, `z-banner`, above everything; the drawer and sheets start below it. |

---

## 6. Accessibility

### 6.1 Focus order (screener, desktop)
1. Skip link ("Skip to results").
2. Header nav.
3. Search.
4. Settings.
5. Screen name.
6. Universe control.
7. Share, Export.
8. Filter rail (rows top to bottom; within a row: metric, operator, threshold, toggle, remove).
9. Add filter.
10. Sieve stages, left to right.
11. Results table (a single tab stop; arrow keys inside).
12. Near misses.
13. Footer.

The drawer traps focus while open and returns focus to the originating row.

### 6.2 Roles

| Component | Roles |
|---|---|
| Results table | `grid` (`row`, `rowheader`, `gridcell`, `columnheader` with `aria-sort`) |
| Drawer, bottom sheets | `dialog` with `aria-modal="true"` |
| Command palette | `combobox` + `listbox` / `option` |
| Histogram handle | `slider` |
| Sieve | `list` of `button`s |
| Tooltips | `tooltip` via `aria-describedby` (existing `Tooltip`) |

### 6.3 Keyboard map

This table replaces `SHORTCUTS` in `ShortcutsHelp.tsx`, and it's added to the README in Phase 5.

| Keys | Where | Action |
|---|---|---|
| `/`, ⌘K / Ctrl+K | Anywhere | Open the command palette |
| `f` | Screener | Add a filter |
| `j` / `k`, ↑ / ↓ | Table, drawer | Next / previous result |
| `Home` / `End` | Table | First / last result |
| `PageUp` / `PageDown` | Table | Move a page |
| `Enter` | Table, palette | Open the drawer |
| ⌘/Ctrl+`Enter`, `o` | Palette; table | Open the full company page |
| `x` | Table, drawer | Pin or unpin for compare (max 3) |
| ← / → (Shift: ×10) | Histogram handle | Move the threshold one bin (ten bins) |
| `Esc` | Drawer, sheet, palette, input | Close, or revert the edit |
| `?` | Anywhere | Show the keyboard map |

Single-letter keys are off while typing in a field.

### 6.4 Live regions
- **One polite region in the screener:** "139 companies, down from 239" after a settled edit, debounced 500ms so dragging doesn't flood screen readers.
- **One for drawer navigation:** "ADBE, Adobe, 12 of 139".
- **Errors** use `role="alert"`.

### 6.5 Contrast and targets
- Every text token meets 4.5:1 on every surface it sits on, including 12px meta (ratios in `docs/design-direction.md`).
- Non-text: `line-strong`, `purple` (with its paper ring), `nodata` and `forest` all meet 3:1.
- Under 768px, every interactive element has a 44×44px hit area (`--touch`), using padding or a pseudo-element when the visual is smaller.
- `prefers-reduced-motion`: the existing global rule stays. The "changed" purple marker becomes a static marker for the same duration; nothing slides.

---

## 7. Copy reference

The copy pass is Phase 4.13; these strings are fixed now so components are built with them.

| Old | New |
|---|---|
| "Why it passed" | "Passes all 5" / "Passes 3 of 5. Fails ROIC, FCF margin." |
| "BINDING" | "removes the most" |
| "ex-SPACs/funds/shells/no-common" | Universe popover: "Operating companies only" (removable) |
| "ex-no XBRL" | "Only companies with XBRL financials" 🔒 |
| "ex-stale" | "Only companies with an annual report from the last 15 months" (from `stale_annual_report_months`) |
| "≥ $1.00M/day" | "Trades at least $1M a day" |
| "Loosen the binding filter: ROIC" | A near-miss-based sentence (§5) |
| "Questions to look into, not verdicts." | Removed. The footer and About page carry the single disclaimer. |
| "18.7% away" | "0.5 pp short" |
| "57.0% sector pct." | "p57", tooltip "better than 57% of Technology" |

The stale rule's "15 months" (`stale_annual_report_months` in `config/thresholds.yaml`) must come through the API, never a literal in code. If the API doesn't expose it yet, that's a Phase 3 contract note.

---

## 8. Open questions for Phase 3

These are contract or computation questions. They don't change any metric value; they're listed here so Phase 3 settles them before building.
1. **Live counts while dragging:** client-side columnar evaluation versus server round-trips (the 50ms target).
2. **Histogram:** explicit `underflow` and `overflow` counts, and an `n/m` split of `null_count`.
3. **Sector medians and percentiles** for every metric on the company page (`MetricGroup`), not just screened ones.
4. **Removing the 100-row cap** (`limit`, up to 1,000 in the contract today) for 5,000 results.
5. **Exposing the stale-filing window** (and other thresholds the copy cites) through `/api/meta`.
