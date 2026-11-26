# Glint UI upgrade brief

You're working in the Glint repo (GitHub: IsharDhaul/glint). Glint is a US stock screener built on SEC XBRL filings, with market prices as a labelled second tier. Its users are retail investors and finance students who scan dozens of tickers quickly.

This brief upgrades the UI substantially and makes it much more interactive. Work through it in phases and stop at each checkpoint.

## Ground rules

- **Read before you write.** Start by mapping the repo and summarise it in 15 lines or fewer before planning. Cover:
  - framework and version (it's Next.js)
  - styling system and component structure
  - where screener state lives
  - how the API and the synthetic mock respond
  - the metric registry
  - the test setup
- **Ask before changing computation.** Don't change how any metric is computed without asking.
  - Display-layer fixes (clipping a histogram's view, number formatting) are fine.
  - Anything that changes a value, a filter result or a sector assignment gets reported to me first.
- **Keep synthetic mode working.** Its banner must stay unmissable.
- **Keep everything URL-addressable.** A screen, its sort, the open drawer and the selected row must all survive a reload and the Share button.
- **Commit at the end of each phase** with a descriptive message. Smaller commits within a phase are fine.
- **Screenshot your work.** If a Playwright or browser tool is available, screenshot each changed screen at 1440px and at 390px width (light theme; there is no dark theme), and critique it against the visual standard below before calling a phase done. If no such tool is available, tell me which screens to check.
- **Know which decisions are mine.** Ask me about visual direction and about removing features. Otherwise decide, log the decision in `docs/ui-decisions.md`, and keep going.

## Visual standard (binding for every phase)

Decided 2026-11-22. Every design doc, spec and line of UI code from Phase 1 on follows this section. If something here conflicts with a later phase, this section wins; if it needs to change, change it here first and log why in `docs/ui-decisions.md`.

### Palette: Forest Green, Sand Beige, hints of Electric Purple

Light theme only. The dark theme and its toggle are removed (approved 2026-11-22). Contrast ratios are WCAG 2.x, measured against sand / paper / dune.

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `sand` (page bg) | `#E8DCC4` | Page background | — |
| `paper` (surface) | `#F6F1E7` | Tables, drawer, panels: where data is read | — |
| `dune` (surface-2) | `#DDCFB2` | Table header, hover, pressed | — |
| `ink` (crisp) | `#16261C` | The headline facts only: ticker, price, market cap, the screen's metric values, sieve counts | 11.6 / 14.0 / 10.3 |
| `ink-soft` | `#344238` | Everything else that is read: body text, labels, metric names, values outside the screen, 10-K facts, home-screen copy | 7.8 / 9.4 / 6.9 |
| `forest` (brand) | `#1F3D2B` | Header bar, primary actions, tickers, the sieve's "kept" fill | 8.8 / 10.6 / 7.7 |
| `muted` | `#4F5345` | Meta text, including 11–12px: as-of times, units, sector medians, sources | 5.8 / 7.0 / 5.1 |
| `sand-soft` | `#B6B49E` | Inactive navigation on the forest band (sand at 75% over forest); the active item is full `sand` (8.8) | 5.7 on forest |
| `purple` (hint) | `#8B5CF6` | Fills only: focus ring, threshold handle, selected-row bar, a count that just changed | 3.1 / 3.8 (non-text) |
| `purple-ink` | `#5B2ED1` | Purple when it must be text (rare) | 5.6 / 6.8 / 4.9 |
| `pos` (blue) | `#17508E` | Positive values | 6.0 / 7.2 / 5.3 |
| `neg` (vermilion) | `#9C3118` | Negative values | 5.4 / 6.5 / 4.8 |
| `caution` (ochre) | `#734600` | Stale data, flags, warnings | 5.9 / 7.2 / 5.2 |
| `nodata` | `#7D735C` | "No data" bars and bins, always hatched | 3.5 / 4.2 (non-text) |
| `line` | `#D2C4A6` | Dividers (decorative) | — |
| `line-strong` | `#7A6D50` | Control borders | 3.7 / 4.5 / 3.3 |
| `banner` | `#D9A441`, diagonal hatch, `ink` text | Synthetic-data banner | ink on banner 7.0 |

Colour rules:
- **Forest is the brand and means "kept".** It never means "up" or "good".
- **Purple is a hint, about 5% of the screen.** It marks where the user is acting (focus, selection, the threshold handle, a count that changed because of their edit) and nothing else. It never encodes data. No purple fills on `dune` (2.8:1). Where purple sits next to forest (the handle on kept bins, 2.8:1) it gets a 2px `paper` ring.
- **Blue up, vermilion down.** Always with a sign and ▲/▼, so colour is never the only signal.
- **Ochre means "look at this"** (stale, flags, warnings, the banner). It is never the brand or a primary action.
- **Missing data is `nodata` plus a hatch;** not meaningful (n/m) is text, never a colour.
- Tints are tokens with alpha. No new hexes in components, no gradients on data, no drop shadows except the one overlay elevation.

### Type: Atkinson Hyperlegible Next for words, IBM Plex for numbers

Self-hosted through `@fontsource` (builds make no network request). Use `@fontsource/atkinson-hyperlegible-next`; if that package isn't available at build time, fall back to `@fontsource/atkinson-hyperlegible` and log it in `docs/ui-decisions.md`.

- **Atkinson Hyperlegible Next carries words:** prose, labels, navigation, the home screen, 10-K facts, tooltips. The Braille Institute designed it for low-vision readers. Look-alike characters are drawn to be told apart (`I`/`l`/`1`, `0`/`O`, `b`/`d`, `rn`/`m`), with open apertures and a generous x-height. Those traits ease reading for everyone. (That's its documented design intent, not a measured eye-strain claim.)
- **IBM Plex Sans carries numbers:** the results table, counts, prices, every metric value. It has compact tabular figures (`font-variant-numeric: tabular-nums` on every number) and a tailed `l`.
- **IBM Plex Mono** is only for formulas, XBRL tags, accession numbers and build ids. It's never used for small labels, prose or tickers.

The two families are deliberately different, one humanist and one engineered, so the split between words and numbers is visible.

| Use | Family | Size / line height | Weight | Tier |
|---|---|---|---|---|
| Page title (company name, screen name) | Atkinson | 24 / 32 | 600 | `ink` |
| Section title | Atkinson | 16 / 24, sentence case | 600 | `ink-soft` |
| Prose | Atkinson | 15 / 24, measure ≤ 70ch | 400 | `ink-soft` |
| Labels, navigation, metric names | Atkinson | 13 / 20 | 400 | `ink-soft` |
| Table body | Plex Sans | 13 / 20, tabular | 400; screened columns 500 | `ink-soft`; screened columns `ink` |
| Table header | Atkinson | 12 / 16, sentence case, no letter-spacing | 500 | `muted` on `dune` |
| Meta text | Atkinson | 12 / 16 | 400 | `muted` |
| Ticker | Plex Sans | 13 / 20; 24 / 32 in page headers | 600 | `forest` |
| Price, market cap, sieve counts | Plex Sans | 20 / 28, tabular | 600 | `ink` |

### Reading comfort: crisp vs soft

Only what a user scans *for* is crisp. Everything they read *around* it is soft. All tiers clear 4.5:1; "soft" means lower contrast inside the accessible range, never faint grey.

| Tier | Token | Gets |
|---|---|---|
| Crisp | `ink`, 500–600 | Ticker (in `forest`), price, market cap, the values of the active screen's metrics, sieve counts |
| Soft | `ink-soft`, 400 | Labels, metric names, values not in the screen, 10-K facts (sector, SIC, fiscal year end, filing dates), flag questions, home-screen and About copy |
| Quiet | `muted`, 400 | As-of times, units, sector medians, sources and accessions, "—" and "n/m" |
| On the band | `sand-soft` / `sand` | Inactive / active navigation |

Rules:
- **Never use weights below 400.** Thin strokes on a warm ground strain the eye.
- **Prose is 15/24 and at most 70 characters wide,** left-aligned. Labels are 13/20.
- **No long runs of italics or all caps.** Emphasis comes from weight or tier, never colour alone.
- **No pure black and no pure white.** Ink is forest-black; surfaces are paper and sand.
- **Low contrast between neighbouring regions** (sand page, paper surfaces, dune headers). The forest band is the only high-contrast block.
- **Crisp is rare.** If more than the scanned-for facts are crisp on a screen, demote the extras to soft.

### Shape, elevation, motion
- **Radius follows hierarchy:** 2px controls, 4px panels and tables, 8px drawer and sheets. Fully rounded only for removable chips.
- **One elevation,** for the drawer, sheets and popovers. Panels are separated by surface colour, not shadow.
- **Motion** is ≤200ms with the `ease-out` token and answers a user action (drawer, count tick, handle). At most one orchestrated moment on first load: the sieve filling. Everything respects `prefers-reduced-motion`.

### Craft rules (binding; added 2026-11-22)
1. **Nested corners.** An inner radius is the outer radius minus the padding between them (`--radius-in-sheet`, `--radius-in-panel`, `.in-sheet`), so curves stay concentric. With Glint's small radii most inner corners come out square.
2. **Borders are alpha.** `--line` is ink at 12% and `--line-strong` ink at 62% (≥ 3:1 on sand, paper and dune), so they blend into any surface. No solid-hex borders.
3. **Palettes in OKLCH.** Tokens are declared in `oklch()`, and derived tokens step L or C from an anchor. Colours meant to weigh the same share one L: up, down and caution all sit at L 45%. `tokens.test.ts` checks contrast and equal L from the stylesheet itself.
4. **Gradients interpolate in OKLCH.** For example `linear-gradient(90deg in oklch, …)`, so they don't go grey in the middle. Single-colour hatches are exempt. Guarded by `no-raw-style.test.ts`.
5. **Icons match their text.** One set (`components/ui/Icon`), 1em, with the stroke set to the adjacent text's stem weight (400 / 500 / 600). No text glyphs or emoji as icons (guarded).
6. **Scrollers fade their clipped edges.** `mask: linear-gradient(90deg, transparent, black 15% 85%, transparent)`, applied only on the sides that hide content (`useScrollEdges`, `.fade-x`), with each fade capped at 4rem.
7. **Icon swaps blur out.** The outgoing icon fades with `filter: blur(4px)` while the new one sharpens in (`IconSwap`, 160ms; instant with reduced motion).
8. **Dark mode, if it ever returns,** shows depth with lighter surfaces, not shadows. Glint is light only for now.
9. **Full-height uses `dvh`**, never `vh` (guarded): 100vh is wrong in mobile Safari.
10. **Product shots on white** use `mix-blend-mode: multiply` so the white disappears on sand or paper. There are no images yet; this applies only to images with true-white grounds.

### Design principles (from the frontend-design guidance)
1. **Ground it in the subject.** Glint's vocabulary is filings, assays and the sieve, not SaaS dashboards.
2. **Spend boldness in one place: the sieve.** Everything around it stays quiet and disciplined.
3. **Type carries the personality.** One family, a deliberate scale, hierarchy through size and weight rather than boxes and colour.
4. **Structure is information.** A border, pill, number or divider must encode something. Non-interactive values are plain text, not pills.
5. **Words are design.** User vocabulary, active verbs, sentence case. Errors say what happened and what to do next; empty states invite the next action.
6. **Remove one accessory.** Before calling a screen done, delete one element it doesn't need.

### Banned defaults
Tracked all-caps eyebrows; a grey explanatory subtitle under every section; middle-dot meta strings (`A · B · C`); "X, not Y" sentences; `→` appended to buttons; identical rounded cards with the same shadow; one radius on everything; monospace for small data labels; fade-and-slide-up entrances; accenting one word of a heading. Keep one disclaimer, in the footer and on the About page.

## What's wrong today (from a design review)

Issues are ranked by impact. The evidence comes from screenshots of the synthetic build and the live build (build 20261031T150633Z).

### Tier 1: trust and the core task

1. **Histograms collapse on real data.** Live ROIC ranges from −17,919% to 575.9%, and gross margin from −36,813% to 15,846%, so each histogram is a single spike. The histogram is how people choose a threshold, so right now it tells them nothing.

2. **Numbers on one company page disagree.** On SYN0113:
   - Revenue (TTM) is $6.98B in Key metrics, but the TTM sparkline ends at $4.31B.
   - Share count change is 11.8% in Growth, but 7.8% and 9.0% in History.
   - Days since last filing is 482 d in the flag and 0 d in Data quality, and the 10-K date implies about 320.
   - Operating margin shows 5.0% in one place and 4.4% in another.

3. **"Why it passed" appears above failures.**
   - SYN0113 fails 2 of its 5 filters under that heading, and SYN0093 fails 4.
   - The mock near misses list passing values as failures:
     - SYN0122 at 47.5% "failed gross margin ≥ 40%"
     - SYN0054 at 30.0% "failed ROIC ≥ 15%"
     - SYN0014 at −1.9x "failed Net debt / EBITDA ≤ 2.0x"

4. **Missing data is the real binding constraint, but it's styled as a footnote.**
   - Live, ROIC removes 3,668 companies, and 2,777 of them have no ROIC at all (about 70% of the universe).
   - The empty state says "Loosen the binding filter: ROIC". Loosening a threshold can't recover missing values, and in that screenshot it was FCF margin that took the count from 239 to 0.
   - The sieve bars are floating segments whose position has no clear meaning.

### Tier 2: scanning speed

5. **There's no ticker search.** The header's prime slot holds the theme and density toggles instead.

6. **Amber is overloaded.** It marks:
   - the brand, the selected state and the primary buttons
   - "binding" and warnings
   - missing-data counts and the "excluded" pill
   - the flag box and the "planned" badges

7. **There's too much scrolling before the answer.**
   - Filter cards are about 210px tall, so only 3 of 5 fit on a laptop screen.
   - On mobile, about 1,500px of filters sit before the first result.
   - The company page puts metadata above the verdict, and Key metrics start about 1,000px down.
   - Metric groups of unequal length leave holes in the grid.
   - The drawer's first screen is metadata.

8. **The results table has gaps.**
   - Right-hand columns are clipped with no scroll affordance.
   - The screen is ranked by ROIC and FCF yield, but there's no score column or sort indicator.
   - The table is capped at "first 100 of 139" with no way to see the rest.
   - ⓘ markers sit after numbers and break decimal alignment.
   - SEC names mix casings: "ADOBE INC.", "UPWORK, INC", "Nutex Health Inc.".
   - "—" and "n/m" both appear with no legend.
   - Some rows have a stray beige cell tint and others don't.

9. **Number formatting looks machine-made.**
   - Thresholds carry trailing zeros: "≥ 40.0%", "2.0x", "$1.00M/day".
   - Percentiles are written as percents: "57.0% sector pct.".
   - "Flags 1.00" should be "1".
   - The input shows "15 %" while the label shows "15.0%".
   - Near misses say "18.7% away", a relative distance, on metrics that are themselves percents.
   - Percentiles have no direction: is the 87th percentile good or bad?

### Tier 3: polish and identity

10. **Internals are leaking.**
    - The Next.js dev badge shows on every screen.
    - The metric dictionary shows P0/P1 and "planned" roadmap badges, and internal enum names like `DERIVED_INPUT`.
    - Explanatory prose is set in monospace.

11. **The universe chips use jargon.**
    - "ex-no XBRL" is a double negative, and "ex-stale" doesn't say what is stale.
    - Some chips have × and some don't, with no explanation.
    - "Binding" is never explained.

12. **Sparklines have no reference points.** There's no zero line, gaps are unexplained, and FY and TTM sit on separate, unlabelled scales.

13. **Semantic colour is inconsistent.**
    - In Growth, only the two "pp" rows get red or green.
    - A share count change of 11.8% isn't flagged, even though the Dilution watch preset flags anything ≥ 10%.

14. **Small stuff.**
    - A "$" price-dependency chip is repeated about 30 times, pressed against labels.
    - The Presets page has three identical cards with three full-width primary buttons.

### Generic / AI-generated tells to remove

- **Copy:** the "X, not Y" construction is everywhere. Examples: "Questions to look into, not verdicts", "Thresholds are starting points, not recommendations", "rows are sampled, not filtered", "Synthetic evidence, not from a filing", "Risk screen (not a buy list)". Keep one disclaimer, in the footer and on the About page.
- **Section headers:** every section has a tracked all-caps label plus a grey sentence explaining itself.
- **Visual kit:**
  - an Inter-like grotesk plus mono, amber on tinted near-black, and a cream light background (about #F3F1EC)
  - identical 1px rounded boxes everywhere
  - pills on everything, including "0" flag counts and every coverage value
  - middle-dot meta strings everywhere
  - the ◆ glyph used as both the logo and the "final count" marker
- **Equal weight everywhere:** 71 metrics sit in 9 identical boxes.

### Keep and strengthen

- The sieve, with its binding filter
- Near misses
- Per-filter missing counts and the "Missing values pass" toggle
- The provenance strip, as-of times and accession numbers
- The metric dictionary
- Sector percentiles per filter
- The drawer plus full-page pattern
- The ticker as a consistent anchor
- The synthetic banner

---

## Phase 0: recon and trust fixes (no visual redesign yet)

Goal: every number on screen is consistent and every heading is honest.

1. **Map the repo,** as described in the ground rules.
2. **Fix the synthetic fixture generator** so it obeys the same invariants as real data:
   - Headline TTM values equal the last TTM series point.
   - Days since filing has a single source of truth.
   - Pass/fail and near-miss lists are computed by the real filter logic, never sampled. If the mock currently samples rows, make it filter a fixture universe instead.
3. **Add invariant tests** that run against the fixtures, and against a real build snapshot if one is available:
   - For revenue, margins and share count change, the last TTM sparkline point equals the headline TTM metric.
   - Any company shown as passing passes every active filter.
   - Every near-miss row fails exactly one filter, and the value shown actually fails it.
   - At every sieve stage, kept + failed + missing equals the previous stage's count.
4. **Check the near-miss distance formula** for `abs()` bugs. Express distance in the metric's own units: pp for percents, x for multiples, $ for dollars.
5. **Make the screen-check heading honest** on the company page and drawer. Use "Passes 3 of 5" and "Fails ROIC, FCF margin", or "Screen check" when there's no screen context.
6. **Investigate sector classification** for MercadoLibre (MELI) and Nutex Health (NUTX), which both show as Industrials. Report their SIC codes and the mapping rule, and propose a fix. Don't apply it without my OK.
7. **Remove leaked internals:**
   - Hide the Next.js dev indicator (`devIndicators` in `next.config`).
   - Strip roadmap badges and internal enum names from user-facing pages.

**Checkpoint:** show me the test results and a list of what changed, then stop.

## Phase 1: design direction (plan only)

Approach this as the design lead at a studio known for giving every client a distinct identity. Glint's one original idea is the sieve: a universe falling through successive filters, with honest accounting of what was removed and why. Ground the identity in that, and in the vernacular of filings, assays and trading terminals rather than SaaS dashboards.

The palette, typeface and theme are fixed by the visual standard above. Write `docs/design-direction.md` with one direction built on them (the original brief asked for two; superseded 2026-11-22). Include:

- **Palette:** the standard's tokens, mapped to every role below (light only). It must cover:
  - one brand accent
  - a caution hue separate from the accent
  - positive and negative data colours that pass colour-blind checks
  - a neutral for "no data"
- **Type:** Atkinson Hyperlegible Next for words, IBM Plex Sans and Mono for numbers and code, per the standard.
  - Requirements: tabular figures, unambiguous 1/l/I and 0/O, compact widths for dense tables.
  - Don't use Inter or another default grotesk.
  - Give the type scale (size, weight, line height) for the page title, section title, table body, table header, small meta text, and numeric emphasis.
- **Layout:** ASCII wireframes for the screener at 1440px and 390px, and the company page at 1440px.
- **One memorable element** (probably the sieve), and how everything around it stays quiet.
- **Self-review:** compare the direction against these defaults and revise anything that matches one without a reason specific to Glint. Say what you changed and why.
  - a cream background near #F4F1EA with a serif display and a terracotta accent
  - near-black with a single bright accent
  - a broadsheet hairline layout
  - identical rounded cards with the same shadow
  - tracked all-caps eyebrows
  - middle-dot meta strings
  - mono for small data labels
  - arrows appended to button text
  - one border radius on everything
  - fade-and-slide-up entrances

**Checkpoint:** stop and let me review the direction.

## Phase 2: handoff spec

Once I've approved the direction, write `docs/ui-spec.md` as a developer handoff. Include:

- **Design tokens,** as CSS custom properties in the existing token system (`web/src/app/globals.css`), with values taken from the visual standard:
  - colour, type, spacing, elevation, and motion durations and easings
  - border radius that varies with hierarchy
  - components reference tokens only, never raw hex or px values
- **Component inventory,** with variants, props and every state: default, hover, focus-visible, active, disabled, loading, empty, error, no data, and not meaningful. Cover these components: FilterRow, Histogram, SieveStage, ResultsTable, DrawerHeader, ScreenCheck, MetricGroup, Sparkline, Chip, CommandPalette, NearMissList.
- **Responsive behaviour** at desktop (>1024px), tablet (768–1024px) and mobile (<768px).
- **Number formatting rules,** all in one module:
  - Thresholds drop trailing zeros.
  - Percents show 1 decimal place in tables, and differences use pp.
  - Multiples use x, and currency is compact ($6.4B).
  - Percentiles show as "p87" with direction text such as "better than 87% of Technology".
  - Counts are integers.
  - "—" means missing and "n/m" means not meaningful, and both get tooltips.
- **Edge cases:**
  - 0 results, 1 result and 5,000 results
  - ROIC missing for 70% of the universe
  - extreme outliers
  - long company names
  - a company opened with no screen context
- **Accessibility:**
  - focus order
  - ARIA roles: grid for the table, dialog for the drawer, combobox for the command palette
  - a keyboard map
  - live-region announcements when counts change
  - 4.5:1 contrast for all text, including 11–12px meta text
  - 44px touch targets on mobile
  - `prefers-reduced-motion` respected

**Checkpoint:** give me a brief summary, and continue unless something needs my call.

## Phase 3: architecture for interactivity

Before building, write a short `docs/interaction-architecture.md` with an ASCII diagram and explicit trade-offs. Cover:

- **State:** one screen-state object, serialised to the URL. It holds filters, universe rules, rank weights, sort, columns, the selected ticker and whether the drawer is open. Derive everything else from it. Choose a URL-state library or hand-roll one, and justify the choice.
- **Computation:** live threshold dragging needs filtering and sieve counts over about 5,000 rows × 70 metrics.
  - Option A: run client-side over a compact columnar payload (typed arrays), optionally in a Web Worker.
  - Option B: run on the server with debounced requests.
  - Target: the sieve and table update within 50 ms of a slider move on a mid-range laptop. Measure it rather than guessing.
- **Histogram binning:** fixed bins over p1–p99 for each metric and universe, plus underflow and overflow counts. Precompute at build time if the payload allows.
- **Data contract:**
  - A value is one of {number, missing, not_meaningful}, each with a reason.
  - Flags carry a severity, and percentiles carry a direction.
  - The type system should enforce all of this.
- **Virtualised table rendering,** so the 100-row cap can go.
- **What you'd revisit** as the data grows.

## Phase 4: build the interactive UI

Build in this order and commit after each item. An item is done when it works by keyboard, at 390px, with reduced motion, and passes the visual standard (palette roles, type scale, banned defaults).

1. **Tokens, type and theme.**
   - Apply the visual standard: tokens (including `ink-soft` and `sand-soft`), Atkinson Hyperlegible Next and IBM Plex via `@fontsource`, the crisp/soft tiers, radius and elevation scale.
   - Remove the dark theme: the `data-theme` attribute, its CSS block, the theme toggle and its localStorage key. Rewrite `docs/DESIGN.md` to match.
   - Remove the generic kit: pills on non-interactive things, identical boxes, all-caps eyebrows, and the explanatory subtitle under every section.
   - Use sentence case for section labels, and move explanations behind an info button.

2. **Ticker search and command palette.**
   - `/` or ⌘K (Ctrl+K) opens it, with fuzzy matching on ticker and name.
   - Enter opens the drawer, and ⌘Enter opens the full company page.
   - It also runs commands: "Apply preset Quality compounders", "Add filter ROIC", "Toggle density".
   - It sits on the right of the header; density moves into a settings menu (there is no theme toggle).

3. **Filter rail.**
   - Each filter collapses to one line: metric, an operator toggle (click to flip ≥/≤), an inline-editable threshold, the kept count, and remove.
   - Expanding a filter shows its histogram with a draggable threshold handle.
     - Dragging updates the sieve and table live.
     - Arrow keys nudge the handle by one bin, and Shift+arrow by ten.
   - The histogram:
     - shows p1–p99 with underflow and overflow bins
     - colours kept bins in the accent and removed bins in a neutral
     - shows a separate "No data: N" bar
   - "Missing values pass" stays as a small toggle showing how many companies it would add ("+2,777").

4. **Sieve as the hero.**
   - Stages run left to right.
   - Each stage's bar shows kept (solid), failed (neutral) and no data (hatched), scaled to the universe.
   - Hover or focus a stage to get a tooltip with exact counts.
   - Clicking a stage temporarily shows the companies removed at that stage, with their values. An "Include these" action relaxes the threshold to the nearest value.
   - Mark the binding stage with a plain label ("removes the most"), and explain "binding" in a tooltip.
   - Count changes animate as a number tick (≤200 ms), only in response to user edits.

5. **Results table.**
   - **Layout:** virtualised rows, a sticky header and ticker column, and a shadow when the table scrolls horizontally.
   - **Ranking and sorting:**
     - a Score column on ranked screens
     - a visible sort indicator, click to sort, Shift-click for a secondary sort
     - a searchable column picker, with the screen's metrics shown by default
   - **Keyboard:** j/k or the arrow keys move the selection, Enter opens the drawer, o opens the full page, and x pins the row for comparison.
   - **Numbers:** decimal-aligned with tabular figures, and status markers in a fixed-width slot.
   - **Names:** normalise display names to title case and drop INC/CORP suffixes in the table. Keep the full legal name in the drawer.
   - **Legend and context:**
     - Explain "—" and "n/m" in a header tooltip.
     - On row hover, show a tiny sector-percentile tick for each screen metric.

6. **Drawer built for fast scanning.**
   - It opens on the right without hiding the ticker column.
   - While it's open, j/k (or ↑/↓) moves to the next or previous result and the drawer updates in place. A user should be able to flick through 40 names without closing it.
   - Content order:
     1. Header: ticker, display name, price, market cap, sector, and the screen check ("Passes 3 of 5 · fails ROIC, FCF margin")
     2. The screen's metrics, with sector-percentile ticks
     3. Flags
     4. History
     5. Metadata, collapsed

7. **Near misses.**
   - Show distance in metric units ("7.5 pp short") and sort by distance.
   - Each row gets a "Relax filter to include" action that edits that filter's threshold and shows the new count.
   - Empty-state advice comes from the near misses ("Lowering FCF margin to 7.4% adds 1 company") instead of naming the filter that removed the most.

8. **Company page.**
   - **Section order:**
     1. Header and screen check
     2. The screen's metrics
     3. Flags
     4. History
     5. Full metric groups, in a CSS columns flow with no holes, collapsible, with the collapsed state remembered
     6. Metadata
     7. Sources
   - **Metric rows:** each shows the value, the sector median and a percentile tick. Metrics in the active screen are highlighted.
   - **Sparklines:**
     - a zero baseline for margins
     - start and end labels
     - a hover crosshair showing value and period
     - gaps marked as missing
     - FY and TTM either share an axis or are clearly labelled as separate scales
   - **Red-flag rules:** cross-reference the presets' rules (for example, dilution ≥ 10%) and flag companies that trip them.
   - **Price-dependent metrics:** one light marker, plus a single legend line explaining it.

9. **Compare.** Pin up to three tickers from the table, the drawer or the palette. A tray at the bottom opens a side-by-side view of their screen metrics and percentiles.

10. **Presets page.**
    - The whole card is clickable.
    - Each card shows a live result count, what the screen looks for, and what it misses.
    - No stack of identical primary buttons.

11. **Metric dictionary.**
    - Formulas in mono, explanations in the sans.
    - No internal enums or roadmap badges.
    - Every entry is deep-linkable, and the info buttons around the app link to it.

12. **Mobile.**
    - Filters collapse into a sticky summary bar ("5 filters · 139 results") that opens a bottom sheet.
    - Results come first.
    - The table shows ticker, short name, score and one chosen metric.
    - Swiping or tapping opens the drawer as a full-screen sheet.

13. **Copy pass.**
    - Use sentence case and plain verbs.
    - Keep one disclaimer, in the footer and on the About page.
    - Remove every "X, not Y" sentence.
    - Rewrite the universe chips in plain language, grouped behind one "Universe" control, with locked rules shown by a lock icon.
    - Errors and empty states say what happened and what to do next.

**Motion:** allow one orchestrated moment on first load at most, such as the sieve filling. All other motion responds to a user action: the drawer slide (≤200 ms), count ticks, and the histogram handle. Respect `prefers-reduced-motion` everywhere.

## Phase 5: verify

- Run the invariant tests, type-check, lint and build.
- Run Lighthouse or axe accessibility checks on the screener, company page, presets and dictionary, and fix any contrast failures.
- Measure slider-drag latency with 5,000 rows and report the number.
- Screenshot every screen at 1440px and 390px. Critique each against this brief and the list of defaults, and fix one more round. Before finishing, remove one unnecessary element from each screen.
- Add the keyboard map to the README.
- Write a final report covering what changed in each phase, anything deferred, and a pointer to the decisions in `docs/ui-decisions.md`.
