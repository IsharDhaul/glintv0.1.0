# Glint UI upgrade: final report

What the upgrade in `docs/glint-ui-upgrade.md` changed, phase by phase, what was measured, and
what is still open. Every non-obvious choice has a dated line in `docs/ui-decisions.md`; this
report doesn't repeat them. Branch: `ui/phase-4-build` (one commit per Phase 4 item, nothing
pushed).

## Phase 0: consistent numbers and honest headings

- Mock mode evaluates screens instead of sampling rows, so the results, the sieve, near misses
  and why-it-passed agree everywhere. The mock serves the synthetic build's own headers, flags
  and history, so the latest TTM point equals the headline.
- Invariant tests over the fixtures:
  - every passing company passes every active filter;
  - every near miss fails exactly one filter, by the value shown;
  - each sieve stage's kept, failed and missing add up to the stage before;
  - the last TTM sparkline point equals the headline.
- Near-miss distance is in the metric's own unit (pp, x, $).
- The screen-check heading says what happened ("Passes 3 of 5", "Fails ROIC, FCF margin"), or
  "Screen check" when there's no screen.
- Internals are off the page: the Next dev badge, roadmap badges and enum names.

## Phase 1: design direction

- **Visual standard:**
  - Forest #1F3D2B for the brand, Sand #E8DCC4 for the page, and Electric Purple #8B5CF6 only
    where the user's hand is.
  - Blue for up, vermilion for down, ochre for caution, hatching for no data.
  - Light theme only.
- **Reading tiers:** crisp ink only for ticker, price, market cap, screened values and sieve
  counts; everything else soft or muted.
- **Type:** Atkinson Hyperlegible Next for words, IBM Plex Sans for numbers, Plex Mono for code.
- **The sieve** is the one memorable element (`docs/design-direction.md`).

## Phase 2: handoff spec

`docs/ui-spec.md` covers:
- tokens, breakpoints and number formatting;
- every component's props and states;
- edge cases, accessibility, a copy reference, and open contract questions.

## Phase 3: architecture for interactivity

`docs/interaction-architecture.md` sets up two things:
- **A live preview in the browser:** a columnar snapshot cached by build, with the same rules as
  the Python engine and a parity test. The server's answer stays authoritative.
- **URL state:** the screen, ticker, drawer and pins.

Measured: 3.1 ms median to evaluate a screen in the browser, against 37–233 ms on the server
before HTTP.

## Phase 4: the interactive UI

| Item | What it delivers |
|---|---|
| 4.1 Tokens, type, theme | One light theme, the three fonts, forest header band, hatched synthetic banner |
| 4.2 Search and palette | `/` or ⌘K over companies, presets, filters and actions; ticker and drawer in the URL |
| 4.3 Filter rail | One line per filter, a draggable histogram threshold, live counts from the first keystroke |
| Craft rules | OKLCH tokens checked for contrast by a test, alpha borders, nested radii, one SVG icon set, blur icon swaps, edge fades, `dvh` |
| 4.4 Sieve | Stages scaled to the universe, hatched no-data, "removes the most", each stage lists what it removed with "Include" |
| 4.5 Results table | Every passing company (virtualised), Score after the name, readable names, aligned decimals |
| 4.6 Drawer | 480px, steps through results with j/k, the screen's metrics with sector-percentile ticks |
| 4.7 Near misses | Grouped by missed filter, gap in the metric's unit, "Include (N)", zero-result advice with a button |
| 4.8 Company page | Sector median and percentile on every metric, collapsible groups, shared time axis, red-flag presets as questions |
| 4.9 Compare | Pin up to three; side by side with pass/fail and percentiles; says when sectors or filers aren't comparable |
| 4.10 Presets page | Whole-card links, live count per preset, risk checks in their own group |
| 4.11 Metric dictionary | What it tells you, formula, when it misleads, copyable links; metric names link here from everywhere |
| 4.12 Mobile and tablet | Filters behind a sticky bar and sheet, results first, one chosen metric column, tap or swipe opens the drawer |
| 4.13 Copy pass | Universe rules in plain words behind one control (excluded count always visible), one disclaimer, errors that say what to do |

## Phase 5: verification

- **Checks:** `make check` passes:
  - engine: 1,240 tests;
  - web: 353 tests in 24 files;
  - ruff, pyright, ESLint and tsc clean.

  All 82 Playwright tests pass in mock mode, and the production build succeeds.
- **Accessibility:** axe (WCAG 2.0/2.1/2.2 A and AA plus best-practice) finds no violations at
  any impact level on any page at 1440 and 390 wide.
  - The CI spec now also scans the universe panel, compare sheet, command palette and the phone
    layouts.
  - Fixed along the way: the screener toolbar sat outside any landmark, and the company page
    skipped a heading level.
- **Contrast:** `tokens.test.ts` checks every text token at ≥ 4.5:1 and every non-text token at
  ≥ 3:1 on all three surfaces, computed from the OKLCH values in the stylesheet.
- **Drag latency with ~6,000 rows** (synthetic 6,000-company build, production build, 5,992
  rows, `web/e2e/real/drag-6k.spec.ts`). The first run was over budget at 4× throttle: p95
  53–75 ms. The urgent funnel-only path was still scoring every passing row. With
  `evaluate(..., { rank: false })`:

  | CPU | Median | p95 |
  |---|---|---|
  | This machine | 17 ms | 30 ms |
  | 4× throttle | 18–23 ms | 30–33 ms |

  The mock-data `make perf` test: 17 ms median and 23 ms p95 at 4× throttle.
- **Screenshot critique:** one round on every screen at 1440 and 390, and one element removed
  from each:

  | Screen | Removed |
  |---|---|
  | Screener rail | Its duplicate "removes the most" |
  | Drawer | The word "Passed" on every row |
  | Company page | Repeated market cap |
  | Presets | A second disclaimer |
  | Dictionary | Two intro sentences that About covers |
  | About | Middle-dot separators |
  | Phone toolbar | Its third row |
  | API-down screen | Skeletons that never resolve |

  Also fixed:
  - long filter names running into the ≥ button, plus a double tab stop on them;
  - the hover tick sticking on touch screens;
  - prose formulas set in mono;
  - "passes all 1 filters".
- **Keyboard map:** in `README.md` under Keyboard, matching the in-app `?` list.

## Deferred, or waiting on a decision

1. **Next.js advisories: done.** Upgraded `next` and `eslint-config-next` 16.4.3 → 16.4.6, which
   clears all seven Next.js advisories. `npm audit` still lists a moderate minimatch issue reached
   through typescript-eslint (dev-only lint tooling); left alone.
2. **Tied percentiles.** Ties take the lowest rank (percent_rank, matching the engine), so a
   sector where every company has a 0% dividend yield shows p0 for all of them. Changing that is
   a computation change. Decision (2026-11-23): keep the lowest rank.
3. **Contract follow-ups:**
   - expose `stale_annual_report_months`, so the universe rule can say "15 months";
   - a Preset `kind` field (red-flag presets are found by their "(red flags)" name today);
   - a structured `misses` field for preset cards;
   - a multi-field `sort` for Shift-click secondary sort.
4. **MELI and NUTX in Industrials.** SEC SIC 7389 is a catch-all that `config/sectors.yaml` maps
   to Industrials (`docs/decisions/WT-09.md`). A per-ticker override was proposed, not applied.
5. **The 42 share-count history mismatches** in the real build (headline vs last history point,
   found by the Phase 0 invariant check). These are for the data pipeline, not the UI.
6. **Preset caveat wording.** Some `config/presets` text still says "not a buy list". That's
   config, outside the UI's paths.
7. **Branches not pushed:** `ui/phase-4-build` and the merged contract branches. Push and open
   PRs when you say so.
