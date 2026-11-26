# WT-12 · saved-screens

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 4 | M | WT-11 | `wt12-saved-screens` | `worktree-wt12-saved-screens` | api 8012 / web 3012 |

**Goal.** Saved screens, run history, "new entrants and leavers since last run", and watchlists, all in `data/user.duckdb`, which pipeline rebuilds never touch.

**Owns.** `engine/glint/user/` (new), `engine/glint/api/routers/user.py` (new router), `web/src/app/saved/`, related components, tests, `docs/decisions/WT-12.md`.

**Contract change needed first.** The v1 models for screens and watchlists already exist from WT-00. If they need changes, use the §8.6 protocol before starting.

**Steps**

0. **Wiring (Wave 4 only, so no parallel conflict):** register a `user` sub-app in `cli.py` and the user router in `api/app.py`, one line each.
1. **`user.duckdb` schema** (§4.7 user tables) with its own `USER_SCHEMA_VERSION` and **forward-only migrations**. Never drop user data. Migration tests run on a copy.
2. **CRUD** for saved screens: save from the current URL state, rename, delete with confirmation, and duplicate.
3. **Run history.** On each new build (or on demand), run every saved screen and store the tickers and counts per `build_id`.
4. **Diff.** Entered and left since the previous run, each with *which filter changed state* and the before/after values.
5. **Watchlists.** Add from the table or drawer. The watchlist view shows flags and metric changes since each ticker was added.
6. **Import/export** of saved screens as JSON (for sharing with Nexus without hosting).
7. **UI:** the `/saved` page, a "Save" button in the top bar, a diff badge ("+4 / −2") on saved screens, and watchlist stars.

**Acceptance criteria**

- [ ] A full `glint refresh` leaves saved screens and watchlists untouched (test, plus a manual check).
- [ ] The diff names the filter responsible for each entry and exit.
- [ ] Migration tests pass, and you can export and import a saved screen round-trip.
- [ ] A backup command: `glint user backup` copies `user.duckdb` to `~/GlintData/backups/` with a date.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-12 (saved-screens).
Your brief: docs/worktrees/WT-12-saved-screens.md. Spec context: docs/SPEC.md §2.14, §4.7, §1.5 rule 9.
User data must survive every rebuild and every migration. Write the "refresh doesn't touch user.duckdb" test first.
```

---

### Wave 4 gate (applies to WT-12…15): v1 and v2 worktrees

> **Gate:** start Wave 4 only after `v0.1.0` is tagged **and** you've used it for 2 weeks. Re-prioritize these four briefs using WT-11's "what was missing" list. They're written to be independent, so do them in any order, no more than 2 at a time.
>
> Two v1 features have no brief yet because their design depends on what you learn in the MVP:
> - **F20** (foreign filers: FX conversion plus ADR ratios, owned by the financials and metrics areas)
> - **F21** (restatement flag)
>
> Write them after v0.1 using the WT-03/WT-06 brief format, as `wt16-foreign-filers` and `wt17-restatements`.
