# Glint design direction: the assay

Phase 1 deliverable for `docs/glint-ui-upgrade.md`. The palette, typeface and theme come from that brief's **Visual standard**, so this document is about how they're used. Nothing here is built yet. Phase 2 turns it into `docs/ui-spec.md`.

## The idea

An assay office takes a sample of ore and reports, line by line, what it contained and what it didn't. Glint does the same to the market. A universe of companies goes into the sieve. Each filter is a tray that keeps some, rejects some, and sets aside the ones it couldn't test because the data isn't there. The report at the end says exactly how many came through and why the rest didn't.

The identity comes from that world: survey green, the colour of paper stock, and the plain, dense typography of a filing. The report is printed in two voices. The figures you came for are crisp; the paperwork around them is softer and easier on the eye. One accent, purple, marks the user's hand: wherever they're adjusting the assay. It doesn't come from SaaS dashboards or from trading-terminal neon.

- **Audience:** retail investors and finance students scanning dozens of tickers quickly.
- **Primary job:** set a few thresholds, see what survives and why, and open the survivors one by one.

## Tokens

### Colour (light only)

| Token | Hex | Where it appears |
|---|---|---|
| `sand` | `#E8DCC4` | Page ground. The app sits on it like papers on a desk. |
| `paper` | `#F6F1E7` | Everything that is read: the table, the drawer, the filter rail, the sieve panel. |
| `dune` | `#DDCFB2` | Table header row, row hover, pressed controls. |
| `ink` | `#16261C` | Crisp: ticker, price, market cap, the screen's metric values, sieve counts. |
| `ink-soft` | `#344238` | Soft: body text, labels, metric names, values outside the screen, 10-K facts, home-screen copy. |
| `forest` | `#1F3D2B` | Header band; primary buttons (with `paper` text); tickers; the "kept" part of every sieve tray and histogram. |
| `sand-soft` | `#B6B49E` | Inactive navigation on the forest band; the active item is full `sand`. |
| `muted` | `#4F5345` | Meta text: as-of times, units, sector medians. |
| `purple` | `#8B5CF6` | The user's hand: focus ring, threshold handle, selected-row bar, a count that just changed from an edit. |
| `purple-ink` | `#5B2ED1` | Purple text, used only for the active item in the command palette. |
| `pos` | `#17508E` | Positive values, always with `+` and ▲. |
| `neg` | `#9C3118` | Negative values, always with `−` and ▼. |
| `caution` | `#734600` | Stale data, flags, warnings. |
| `nodata` | `#7D735C` | "No data" in the sieve and histograms, always with a 45° hatch. |
| `line` | `#D2C4A6` | Dividers between rows and sections. |
| `line-strong` | `#7A6D50` | Input and button borders. |
| `banner` | `#D9A441` + hatch | Synthetic-data banner only. |

### How each role is covered

| Role the brief asks for | Token |
|---|---|
| Brand accent | `forest`, with `purple` reserved for interaction |
| Caution, separate from the accent | `caution` (ochre) |
| Positive / negative data, colour-blind safe | `pos` blue / `neg` vermilion. They differ in hue and in lightness, and every value carries a sign and an arrow. |
| A neutral for "no data" | `nodata` + hatch |

### Type: Atkinson Hyperlegible Next for words, IBM Plex for numbers

| Use | Family | Size / line height | Weight | Tier |
|---|---|---|---|---|
| Page title | Atkinson | 24 / 32 | 600 | `ink` |
| Section title | Atkinson | 16 / 24, sentence case, nothing above or below it | 600 | `ink-soft` |
| Prose | Atkinson | 15 / 24, ≤ 70ch | 400 | `ink-soft` |
| Labels, navigation, metric names | Atkinson | 13 / 20 | 400 | `ink-soft` |
| Table body | Plex Sans | 13 / 20, `tabular-nums`, right-aligned on the decimal | 400; screened columns 500 | `ink-soft`; screened columns `ink` |
| Table header | Atkinson | 12 / 16, sentence case, no letter-spacing | 500 | `muted` on `dune` |
| Meta text | Atkinson | 12 / 16 | 400 | `muted` |
| Ticker | Plex Sans | 13 / 20; 24 / 32 in page headers | 600 | `forest` |
| Price, market cap, sieve counts | Plex Sans | 20 / 28, tabular | 600 | `ink` |
| Mono | Plex Mono | 12 / 16 | 400 | Formulas, XBRL tags, accession numbers, build ids; nothing else |

Atkinson is the reading face. It was designed by the Braille Institute so look-alike characters can't be confused, with open shapes and a large x-height. Plex is the counting face: compact tabular figures for dense columns. Words and numbers look different on purpose. A ticker is a name, but it is matched character by character, so it's set in Plex 600, not mono.

### Shape, elevation, spacing, motion
- **Radius:** 2px for inputs, buttons and table cells' focus outline; 4px for panels, the table frame and popovers; 8px for the drawer's leading corners and the mobile bottom sheet. Removable universe rules are the only fully rounded elements.
- **Elevation:** one shadow, `0 8px 24px rgb(22 38 28 / 0.18)`, used only by the drawer, sheets, popovers and the command palette. Panels are set apart by `paper` on `sand`, not by shadow.
- **Spacing:** 4px base. Panels 16px inside, 24px between major regions. Table rows 32px (compact) or 40px (comfortable).
- **Motion:** 160ms `ease-out` for the drawer and sheets, 200ms for count ticks, instant for the threshold handle. The single first-load moment: the sieve trays fill left to right once, 400ms in total. Reduced motion shows the final state immediately.

## Crisp and soft

What a user scans *for* is crisp: ticker, price, market cap, and the values of the metrics in their screen. Everything around those facts is soft (`ink-soft`, weight 400) or quiet (`muted`). All three tiers stay above 4.5:1; soft means calmer, not faint.

```
Company page header
  ADBE  Adobe                                   $512.40        $221B        ← crisp: Plex 600, ink (ticker in forest)
  Technology, Nasdaq                            price          market cap   ← soft: Atkinson 400, ink-soft / muted labels
  Fiscal year ends Nov 30.  Latest 10-K filed 15 Jan 2025.                  ← soft: 10-K facts, ink-soft
  Filings as of 2 Jan 2026                                                  ← quiet: muted

Results row (screen on ROIC and gross margin)
  ADBE   Adobe        Technology    $221B    31.2%    88.0%    4.1%    22.4x
  ^crisp ^soft        ^soft         ^crisp   ^crisp   ^crisp   ^soft   ^soft
                                    mkt cap  screened columns  not in the screen

Header band (forest)
  Glint    Screener    Presets   Metrics   About         [ / Search ]
           ^sand        ^sand-soft (inactive)
```

The home screen follows the same split. The screen name, the sieve counts and the results' crisp columns are what the eye lands on. The universe description, the as-of line, filter labels, near-miss explanations and the footer are soft or quiet.

## The memorable element: the sieve

Everything else is quiet so the sieve can be read at a glance.

```
 Universe          ROIC ≥ 15%          Gross margin ≥ 40%     FCF margin ≥ 10%
 5,412             1,744               902                    139
 ████████████████  ██████▒▒▒▒░░░░░░░░  ███▒▒▒░░░░░░░░░░░░░░░  █▒▒▒░░░░░░░░░░░░░░░░
                   removes the most
                   2,777 have no ROIC

 █ kept (forest)   ▒ failed the test (line)   ░ no data (nodata, hatched)
```

- Every tray is drawn at the same width: the full universe. You can see how much is left after each step, because the remaining part shrinks against the same frame.
- Kept is forest, failed is a flat sand-grey (`line`), and no data is hatched `nodata`. The count above each tray is numeric emphasis.
- The binding tray carries a plain label, "removes the most". Under it, the cause is stated when missing data dominates: "2,777 have no ROIC". That's Glint's honesty about missing data, made visible where people look.
- When an edit changes a count, the number ticks (200ms) and is underlined in `purple` for 1.5s: the user's hand, briefly visible. Nothing animates on its own after first load.
- Hover or focus on a tray shows the exact kept / failed / no-data counts. Clicking a tray lists the companies it removed.

Around it, everything stays plain:
- Filters are single lines of text, not cards.
- Universe rules sit behind one "Universe" control.
- The table has no zebra striping, no row borders except `line`, and no pills on values.

## Layout

All content is left-aligned. Numbers are right-aligned in their columns. Nothing is centred except empty states.

### Screener, 1440px

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ ////  Synthetic data: these are not real companies  //////////////////////////////////////// │ banner (mock only)
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Glint    Screener   Presets   Metrics   About                [ /  Search ticker or company  ] │ forest band, sand text
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Quality compounders ▾                        Universe: 5,412 US companies ▾    Share   Export │ on sand
│ Filings as of 2 Jan 2026, prices close 1 Jan                                                 │ meta
├────────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ Filters                    │  5,412      1,744        902         410         239       139  │ the sieve (paper)
│ ROIC          ≥  15%  1,744│  ███████    ███▒▒░░░     ██▒░░░░     █▒░░░░░     █░░░░░   █░░░  │
│ Gross margin  ≥  40%    902│             removes the most: 2,777 have no ROIC                │
│ Rev CAGR 3y   ≥   8%    410├─────────────────────────────────────────────────────────────────┤
│ Net debt/EBITDA ≤ 2x    239│ 139 companies, ranked by score                     Columns ▾    │
│ FCF margin    ≥  10%    139│ Ticker  Name              Sector        Score   ROIC   GM    FCF │ dune header
│                            │ ADBE    Adobe             Technology     0.91  31.2%  88.0%  …   │ paper rows
│ + Add filter               │▌MSFT    Microsoft         Technology     0.89  29.8%  69.4%  …   │ ▌ purple = selected
│                            │ …                                                   (virtualised)│
│ Missing values pass (+2,777)├────────────────────────────────────────────────────────────────┤
│                            │ Near misses                                                     │
│                            │ SYN0232  Synthetic 0232   FCF margin 9.5%, 0.5 pp short   Relax │
└────────────────────────────┴─────────────────────────────────────────────────────────────────┘
  Educational tool. Not investment advice.                    Data: SEC XBRL filings; prices EOD
```

- The filter rail is 280px wide. Each filter is one line: metric, an operator you can click to flip, an editable threshold, the kept count. The remove control appears on hover or focus. Expanding a line reveals its histogram.
- The drawer opens over the right 480px and leaves the ticker column visible.

### Screener, 390px

```
┌────────────────────────────────────┐
│ //// Synthetic data //////////////  │
│ Glint                     [ / ]     │ forest band; search opens full-screen
├────────────────────────────────────┤
│ Quality compounders ▾               │
│ 5 filters, 139 results     Filters  │ sticky; "Filters" opens the bottom sheet
│ ███▒▒░░░░░  ▸ removes most: ROIC    │ one-line sieve summary
├────────────────────────────────────┤
│ Ticker  Name            Score  ROIC │
│ ADBE    Adobe            0.91 31.2% │ 44px rows, tap opens the full-screen drawer
│ MSFT    Microsoft        0.89 29.8% │
│ …                                   │
├────────────────────────────────────┤
│ Near misses (18)                  ▸ │
└────────────────────────────────────┘
```

Results come first. The full sieve and filters live in the bottom sheet, which has an 8px radius and the single elevation.

### Company page, 1440px

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Glint    Screener   Presets   Metrics   About                [ /  Search ticker or company  ] │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ ← Quality compounders                                                                        │
│                                                                                              │
│ ADBE  Adobe                                                     $512.40       $221B          │ title + numeric emphasis
│ Technology, Nasdaq                                              price         market cap     │
│                                                                                              │
│ Passes 4 of 5. Fails FCF margin.                                                             │ screen check (neg text)
├──────────────────────────────────────────────────┬───────────────────────────────────────────┤
│ This screen's metrics                            │ Flags                                     │
│ ROIC            31.2%   median 12.1%  ──────●──  │ Share count is up 11.8% in a year.        │
│ Gross margin    88.0%   median 54.0%  ───────●─  │ What's driving the dilution?              │
│ FCF margin       9.5%   median 11.0%  ────●────  │  (caution rule on the left edge)          │
├──────────────────────────────────────────────────┴───────────────────────────────────────────┤
│ History                                                                                      │
│ Revenue (TTM)       $4.3B ╱‾‾╲_╱‾‾‾ $7.0B      Operating margin   0% ┄┄┄┄┄┄┄┄  4.4%           │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ All metrics  (CSS columns, collapsible groups; remembered)                                    │
│ Valuation          │ Profitability       │ Growth                                            │
│ P/E      22.4x     │ ROE      41.0%      │ Revenue growth  +11.2% ▲                          │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Company details ▸   (collapsed)                                                              │
│ Sources: 10-K 0000796343-25-000012, filed 2025-01-15  (accessions in mono)                   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Percentile tick:** a `line-strong` track with a `forest` dot, and "better than 87% of Technology" on hover or focus. Purple stays for interaction.
- **Metrics in the active screen** get a 2px `forest` rule on the left, not a background tint.

## Components in brief

These are Phase 2's starting points.
- **Buttons:**
  - Primary: `forest` with `paper` text, 2px radius, no arrow.
  - Secondary: `paper` with a `line-strong` border.
  - Ghost: text only.
  - Focus is a 2px `purple` ring with a 2px offset.
- **Filter line:** text, not a card. The metric label is soft (Atkinson 13, `ink-soft`); the threshold and kept count are Plex, right-aligned. The binding filter's count is printed in `ink` 600 with "removes the most" beside it.
- **Results table:** `dune` header, `paper` rows, `line` dividers. Hover is `dune` at 50%. The selected row gets a 3px `purple` bar on the left plus `dune`. Status markers (ⓘ, flags) sit in a fixed 16px slot left of the number, so decimals stay aligned.
- **Flags:** the question is soft prose (Atkinson 15/24, `ink-soft`), evidence values in Plex, evidence labels `muted`, and a 2px `caution` rule on the left. No filled boxes.
- **Null values:** "—" for missing and "n/m" for not meaningful, both quiet (`muted`), each with a tooltip. The table header's tooltip explains both.
- **Synthetic banner:** `banner` with a diagonal hatch and `ink` text, full width above the header, in every view. It can't be hidden, and nothing else in the app uses ochre fill.

## Self-review against the defaults

| Default | Verdict |
|---|---|
| Cream background near #F4F1EA, serif display, terracotta accent | **Partly close, kept for a reason.** Sand is the user's own choice, and it's deeper and more yellow than the cream default (#E8DCC4 against #F4F1EA). The rest of the cliché is absent: no serif (Plex Sans throughout), no terracotta. The accent is forest, with purple for interaction. Changed: data surfaces moved from sand to `paper`, so tables read crisply rather than "vintage". |
| Near-black with a single bright accent | **Avoided.** Light only; purple is limited to about 5% of the screen and always means "your hand". |
| Broadsheet hairline layout | **Avoided.** Regions separate by surface (`paper` on `sand`), not by hairline rules. Dividers exist only between table rows. |
| Identical rounded cards with the same shadow | **Removed.** Filter cards become single lines; metric groups use CSS columns with headings, not boxes. There's one shadow, for overlays only. |
| Tracked all-caps eyebrows | **Removed.** Section titles are 16px sentence case. Table headers are 12px sentence case with no tracking. |
| Middle-dot meta strings | **Removed.** Meta uses commas and sentences ("Technology, Nasdaq"; "5 filters, 139 results"). Changed: the mobile summary bar was drafted with a middle dot and now uses a comma. |
| Mono for small data labels | **Removed.** Mono is only for formulas, tags, accessions and build ids. Tickers moved from mono to Plex Sans 600. |
| An Inter-like grotesk for everything | **Avoided.** Two clearly different families, each chosen for a job: Atkinson Hyperlegible Next (humanist, built for legibility) for words, IBM Plex Sans (engineered, compact tabular figures) for numbers. |
| Everything at full contrast | **Avoided.** Three tiers (crisp, soft, quiet); only the facts a user scans for are crisp. |
| Arrows appended to button text | **Removed.** "←" survives only on the back link, where it points somewhere. Arrows in the sieve diagram describe flow. |
| One border radius on everything | **Avoided.** 2 / 4 / 8px by hierarchy, and full rounding only for removable rules. |
| Fade-and-slide-up entrances | **Avoided.** One first-load moment (the sieve fills); everything else answers an action. |
| Accenting one word of a heading | **Avoided.** Headings are one colour, one weight. |
| A solid brand header band | **Kept on purpose.** It works like the cover band of a filing, it carries the search (the most-used control), and it's the one big area of forest that tells you whose product this is. |

**Remove one accessory:** the earlier draft had a forest left border on the whole drawer. It's cut: the drawer's elevation already separates it.

## Contrast check

WCAG 2.x relative luminance, computed by script on 2026-11-22. Format: against `sand` / `paper` / `dune`.

| Foreground | Ratio | Requirement |
|---|---|---|
| `ink` | 11.6 / 14.0 / 10.3 | text ≥ 4.5 ✓ |
| `ink-soft` | 7.8 / 9.4 / 6.9 | text ≥ 4.5 ✓ |
| `forest` | 8.8 / 10.6 / 7.7 | text ≥ 4.5 ✓ |
| `muted` | 5.8 / 7.0 / 5.1 | text ≥ 4.5 ✓ (11–12px meta included) |
| `purple-ink` | 5.6 / 6.8 / 4.9 | text ≥ 4.5 ✓ |
| `pos` | 6.0 / 7.2 / 5.3 | text ≥ 4.5 ✓ |
| `neg` | 5.4 / 6.5 / 4.8 | text ≥ 4.5 ✓ |
| `caution` | 5.9 / 7.2 / 5.2 | text ≥ 4.5 ✓ |
| `purple` | 3.1 / 3.8 / 2.8 | non-text ≥ 3 on sand and paper ✓; never filled on dune |
| `nodata` | 3.5 / 4.2 / 3.0 | non-text ≥ 3 ✓ |
| `line-strong` | 3.7 / 4.5 / 3.3 | control borders ≥ 3 ✓ |

Other pairs:
- `paper` text on `forest`: 10.6.
- `sand` text on `forest` (header band): 8.8.
- `sand-soft` (inactive navigation) on `forest`: 5.7.
- `paper` on `purple-ink`: 6.8.
- `ink` on `banner`: 7.0.
- `purple` against `forest`: 2.8, so the threshold handle gets a 2px `paper` ring where it sits on kept bins.
