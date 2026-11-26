# WT-05 · web-ui

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 1 | L | WT-00 | `wt05-web-ui` | `worktree-wt05-web-ui` | web 3005 |

**Goal.** The whole Glint interface, built against **mock mode**: shape-correct synthetic responses and an unmissable SYNTHETIC banner. It will switch to the real API in WT-09 with no component changes.

**Owns.** `web/` (except `src/lib/api/types.ts`), `docs/DESIGN.md`, `docs/decisions/WT-05.md`.

**Must not touch.** `engine/`, contracts and the generated types.

**Steps**

1. **Design pass with you first.**
   - Turn §3.4 into `docs/DESIGN.md` and Tailwind tokens.
   - Build one static "kitchen sink" page (`/dev/kitchen-sink`) with buttons, chips, a table, the sieve, a drawer, both themes and both densities.
   - **Get your sign-off on the look before building features.**
2. **Data layer.**
   - A typed client (`openapi-fetch` over the generated types) wrapped in TanStack Query hooks.
   - **Mock mode** (`NEXT_PUBLIC_GLINT_MOCK=1`): MSW handlers serve `web/mocks/*` and generate *shape-correct* screen responses. They return rows sampled from synthetic companies, sieve steps named after the request's filters with decreasing counts, and requested columns present.
   - Mock mode **never pretends to filter correctly**. It only exercises UI states. The banner is always visible.
3. **Units and formatting.** `units.ts` handles display↔fraction conversion and `format.ts` the per-unit formats (§3.3), with exhaustive unit tests. Nothing else formats numbers.
4. **Layout:** a top bar (universe chips, presets, export, share, as-of line), the filter panel, the main area (sieve, table, near misses) and a right drawer.
5. **Filter builder:**
   - A metric picker (search, category groups, definition and unit preview).
   - A comparator select limited to valid ones.
   - A unit-aware value input.
   - A distribution histogram under the input (from `/api/distribution`) with a threshold marker and pass count.
   - AND groups plus one level of OR group in the UI, and a `missing` toggle.
6. **Results table:**
   - TanStack Table + Virtual, with a column picker, sorting and a pinned ticker column.
   - "—" vs "n/m" with reason tooltips, a flag count and a coverage badge.
   - Clicking a row opens the drawer.
7. **Sieve bar:** stacked trays with counts and `−k missing`, the binding step highlighted, and clicking a step scrolls to its filter.
8. **Near misses** panel.
9. **Company drawer** (§2.9) and the `/company/[ticker]` page: metrics by category, Recharts sparklines, flags as questions, source links and why-passed.
10. **Pages:** `/presets`, `/metrics` (dictionary from the registry), `/about` (placeholder content; WT-10 fills it).
11. **URL state:** Screen JSON ↔ `?s=` (lz-string), debounced, with back/forward undo.
12. **States and accessibility:** loading, empty (suggest loosening the binding filter), API down, no build, and keyboard shortcuts (§3.3). Reduced motion and focus rings.
13. **Tests:** Vitest for units, format and the URL codec. Playwright (mock mode): load, add a filter, apply a preset, open the drawer, export CSV, reload the share URL.

**Acceptance criteria**

- [ ] You've signed off the kitchen-sink page, recorded in the decisions file with the date.
- [ ] Every number in the UI passes through `format.ts`. A lint rule or grep test enforces no `toFixed` or `toLocaleString` elsewhere.
- [ ] No raw colors in components; tokens only. Both themes and both densities work.
- [ ] Usable at 1280–1600 px. At 390 px there's no horizontal *page* scroll (the table scrolls inside its container).
- [ ] Everything is reachable by keyboard. Shortcuts work, and reduced motion disables animation.
- [ ] The SYNTHETIC banner shows on every page in mock mode, and you can't hide it.
- [ ] Playwright passes in CI (mock mode).

**Demo:** `PORT=3005 NEXT_PUBLIC_GLINT_MOCK=1 make dev-web`. Screenshots of the screener, drawer, metrics page, light theme and empty state go in the PR.

**Decisions to record:** the final palette and fonts; table library settings; anything in the DSL you found awkward in the UI. Don't change it; propose it via §8.6.

**Gotchas**

- Never compute or "fix" metrics in the browser. Display only.
- Unit conversion happens in exactly one place.
- Keep Recharts out of the table rows (performance). Sparklines belong in the drawer only.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-05 (web-ui).
Your brief: docs/worktrees/WT-05-web-ui.md. Spec context: docs/SPEC.md Part 3, §2.5–2.12, §5.5.
Step 1 is a design pass: build the kitchen-sink page and stop for my sign-off before any feature work.
Use mock mode only (PORT=3005). Mock responses are shape-correct but must never look like real filtering or real companies.
```
