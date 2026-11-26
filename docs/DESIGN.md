# Glint design

The binding rules are the **Visual standard** in `docs/glint-ui-upgrade.md`. The direction ("the assay") is in `docs/design-direction.md`, and the component handoff is `docs/ui-spec.md`. This page is the short reference for anyone touching the UI.

The tokens live in `web/src/app/globals.css`. The living reference is `/dev/kitchen-sink`.

Components use token classes only (`bg-paper`, `text-ink-soft`, `text-label`, `rounded-panel`, …), never a raw colour, size, `uppercase` or `tracking-*`. `web/src/lib/no-raw-style.test.ts` enforces this, alongside `no-stray-formatting.test.ts` for numbers.

## Concept: the assay

A universe of companies falls through the sieve. Each filter keeps some, rejects some, and sets aside the ones it couldn't test because the data isn't there. The sieve is the one memorable element; everything around it stays quiet.

## Colour (light only)

Every text token meets **4.5:1** on `sand`, `paper` and `dune`. Ratios are listed in `docs/design-direction.md`.

| Token | Hex | Use |
|---|---|---|
| `sand` | `#E8DCC4` | Page ground |
| `paper` | `#F6F1E7` | Everything that is read: tables, drawer, panels, inputs, popovers |
| `dune` | `#DDCFB2` | Table header, hover (at 50%), pressed |
| `ink` | `#16261C` | **Crisp:** ticker-adjacent facts (price, market cap), the screen's metric values, sieve counts |
| `ink-soft` | `#344238` | **Soft:** labels, prose, 10-K facts, values outside the screen |
| `muted` | `#4F5345` | **Quiet:** meta, units, medians, sources, `—` and `n/m` |
| `forest` | `#1F3D2B` | Brand: header band, primary buttons, tickers, "kept", passed checks |
| `on-forest` / `sand-soft` | `#F6F1E7` / `#B6B49E` | Text on the band: active / inactive navigation |
| `purple` | `#8B5CF6` | The user's hand only: focus ring, selected row, threshold handle, a row an edit brought in. Never data. |
| `purple-ink` | `#5B2ED1` | Purple as text (rare) |
| `pos` / `neg` | `oklch(45% 0.118 253.9)` / `oklch(45% 0.147 34.3)` | Up (blue) / down (vermilion), always with a sign and ▲/▼. `neg` also marks failed checks and errors. |
| `caution` | `oklch(45% 0.095 68.7)` | Stale, flags, warnings |
| `nodata` | `#7D735C` | No-data bars, always hatched (`.hatch`) |
| `line` / `line-strong` | ink at 12% / 62% (alpha) | Dividers / control borders |
| `banner` | `#D9A441` | Synthetic-data banner (`.banner-hatch`), the only ochre fill |

Colour rules:
- **Forest never means "up".** Blue does.
- **Purple never encodes data.**
- **Missing data is hatched, never colour alone.**
- **Panels are separated by surface** (paper on sand), not by 1px boxes or shadows.

## Type

| Family | Token | Carries |
|---|---|---|
| Atkinson Hyperlegible Next | `font-words` (the body default) | Prose, labels, navigation, 10-K facts |
| IBM Plex Sans | `.num`, `table`, decimal inputs | Every number, with tabular figures; tickers at 600 |
| IBM Plex Mono | `font-code` | Formulas, XBRL tags, accession numbers, build ids. Nothing else. |

All three are self-hosted via `@fontsource`. No weight goes below 400.

| Class | Size / line height | Use |
|---|---|---|
| `text-title` | 24/32 | Page title |
| `text-section` | 16/24 | Section titles, sentence case. Explanations go in an `InfoTip`, never a subtitle. |
| `text-prose` | 15/24 | Prose; wrap in `max-w-prose` |
| `text-label` | 13/20 | Labels, navigation, buttons |
| `text-cell` | 13/20 | Table cells |
| `text-head` / `text-meta` | 12/16 | Table headers / meta |
| `text-figure` | 20/28 | Price, market cap, sieve counts |

## Shape, elevation, motion

- **Radius by hierarchy:** `rounded-control` (2px), `rounded-panel` (4px), `rounded-sheet` (8px). Fully round only for removable or toggleable chips.
- **Elevation:** `shadow-overlay`, used only by the drawer, popovers, tooltips and dialogs.
- **Focus:** `--focus-ring` gives a 2px paper gap, then 2px purple, on `:focus-visible`.
- **Motion:**
  - It's 200ms or less, uses the `ease-out` curve, and answers a user action (drawer, count tick, handle).
  - A row an edit brought in gets `.entered`: a purple left bar that fades over 1.5s, or stays static under `prefers-reduced-motion`.
  - The reduced-motion rule turns off every other animation and transition globally.

## Craft rules

These are binding; the full wording is in the Visual standard.
- **Nested corners:** inner radius = outer − padding (`rounded-in-sheet`; `.in-sheet` does it for panels inside the drawer).
- **Borders:** `line` and `line-strong` are ink with alpha (12% / 62%), never solid hexes.
- **Colour:** tokens are OKLCH. Up, down and caution share L 45%. Gradients interpolate `in oklch`.
- **Icons:** only `Icon` / `IconSwap`, 1em, stroke matched to the text weight (`weight={400|500|600}`). Swaps blur the outgoing icon.
- **Horizontal scrollers:** `FadeScroller` or `useScrollEdges` + `.fade-x` (`.fade-x-end` for tables with a sticky first column).
- **Viewport units:** `dvh` only.
- **Not used yet:** dark mode, if added, gets depth from lighter surfaces; product shots on white get `mix-blend-mode: multiply`.

## Density

Density is `data-density="compact" | "comfortable"` on `<html>`, persisted in localStorage and applied before first paint by `PREFS_SCRIPT`.

| Token (class) | Compact | Comfortable |
|---|---|---|
| `--row-h` (`h-row`) | 32px | 40px |
| `--ctl-h` (`h-ctl`) | 28px | 36px |
| `--cell-x` (`px-cell`) | 8px | 12px |
| `--panel-pad` (`p-panel`) | 12px | 16px |

There's one theme. No `data-theme` attribute exists.

## Components (web/src/components/ui)

| Component | Notes |
|---|---|
| `Button`, `IconButton` | Primary (forest), secondary (paper + `line-strong` border), ghost. No arrows in labels. `IconButton` requires a label. |
| `Chip` | Only for removable (`onRemove`), toggleable (`onToggle`, `pressed`) or locked (`locked`, `lockReason`) things. Anything static is plain text. |
| `Tooltip`, `InfoTip` | Open on hover *and* keyboard focus, linked with `aria-describedby`. `InfoTip` is the ⓘ beside a heading. |
| `NullValue`, `InfoMark` | `—` missing, `n/m` not meaningful, ⓘ for info notes. Each has a plain-language reason (never a raw code). |
| `SieveBar`, `Histogram` | Being rebuilt in Phase 4 items 3–4 (`docs/ui-spec.md` §4.2–4.3). |
| `Drawer` | Right side, `role="dialog"`, 8px leading corners, `shadow-overlay`. Esc and the backdrop close it; focus is trapped, then returned. |

## Accessibility

- Text meets 4.5:1. Controls, focus and no-data bars meet 3:1.
- Table headers have `scope`; sortable headers use `aria-sort`.
- No information depends on colour alone. "removes the most" is a label, changes carry a sign and arrow, nulls have glyphs, and pass/fail carries ✓/✗ and words.
