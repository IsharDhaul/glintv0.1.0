# WT-07 · pipeline ★

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 2 | M | WT-01, WT-02, WT-03 (merge **after** WT-06) | `wt07-pipeline` | `worktree-wt07-pipeline` | — |

**Goal.** One command, `glint refresh`, that rebuilds everything safely: build-then-swap, incremental skips, a run report, and the previous build preserved on failure.

**Owns.** `engine/glint/pipeline/`, `scripts/launchd/`, `engine/tests/pipeline/`, `docs/decisions/WT-07.md`.

**Must not touch.** Stage internals (call each module's public `Stage`), contracts.

**Steps**

1. **Stage registry.** Wrap each module's entry point as a `Stage` from `contracts/pipeline.py`:
   - `download_sec` → `extract_facts` → `companies` → `financials` → `prices` → `price_stats` → `metrics` → `flags_quality` → `archive_snapshot` → `publish`

   Until WT-06 merges, `metrics` is a stub stage that fails clearly.
2. **Runner.** Resolves dependencies, times each stage, collects `StageResult`s and writes `pipeline_runs`. Options: `--only`, `--from`, `--no-download`, `--skip-prices`, `--dry-run`.
3. **Build-then-swap.**
   - Write to `data/builds/<build_id>.duckdb` (where `build_id` = UTC timestamp).
   - On success, atomically replace `data/current.json` (write a temp file, then `os.replace`).
   - Keep the last 2 builds.
   - **Never open `user.duckdb`.** A test asserts it.
4. **Incremental logic:**
   - Skip the SEC download and extract when the manifest shows unchanged sources and a previous extract exists.
   - Prices fetch only missing dates.
   - Financials and metrics always recompute (fast).
5. **Failure handling.** If any stage fails, abort, keep the current build live, print the failing stage with the error and log path, and exit non-zero.
6. **Run report.** A console and markdown summary in `data/reports/<build_id>.md`:
   - Durations per stage and counts
   - Universe size
   - Coverage per line item and null rate per P0 metric, **compared with the previous build**. Drops of more than 2 pp are warnings (§4.6).
7. **Schedule (optional).** `scripts/launchd/com.glint.refresh.plist.template` at 09:15 London, logging to `~/GlintData/logs/`. `make schedule-install` and `make schedule-remove` manage it. It's documented, but not installed automatically.
8. **Timing.** Measure a cold run (`--skip-prices` if the backfill is not done), a warm run, and `--no-download`. Record all three against the §4.8 targets.

**Acceptance criteria**

- [ ] A cold `glint refresh` completes on your Mac, and the times are recorded.
- [ ] A second run the same day skips the SEC stages (shown in the report).
- [ ] **Kill test:** kill the process mid-`metrics`. `current.json` still points to the previous build, and the API (if running) keeps serving it.
- [ ] A test proves `user.duckdb` is never opened in write mode.
- [ ] The run report is produced, with the previous-build comparison.
- [ ] `--no-download` rebuilds from shared raw in a fresh worktree (this is how other worktrees get real data).

**Demo commands:** `glint refresh --dry-run` · `glint refresh` · `glint refresh --no-download` · `cat data/reports/<latest>.md`.

**Decisions to record:** stage order changes; real timings; retention policy.

**Gotchas**

- DuckDB allows one writer per file. The API opens builds read-only, and swaps are pointer flips, never in-place writes.
- Timezones: store UTC, and display London or ET explicitly.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-07 (pipeline).
Your brief: docs/worktrees/WT-07-pipeline.md. Spec context: docs/SPEC.md §4.2, §4.6–4.8, §5.7.
Call each module only through its Stage. Until WT-06 is merged, the metrics stage is a stub — don't implement metrics here.
The kill test is mandatory: show me it working.
```
