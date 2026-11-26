# Part 8: Worktree playbook

In WT-00 this part gets copied to `docs/worktrees/README.md`. Every worktree prompt points to it.

## 8.1 How worktrees work in Claude Code

- **Start a session in a new worktree:** `claude --worktree <name>` (or `-w <name>`). Claude Code creates `.claude/worktrees/<name>/` on a new branch called `worktree-<name>`.
  - In the **desktop app**, pick the *worktree* option when you start a session in the Glint folder. It does the same thing.
- **Base branch:** by default the worktree branches from the remote default branch (`origin/main`). Claude Code only auto-fetches if the repo hasn't been fetched in 24 hours. So **always `git fetch origin` in the main checkout before starting a worktree**, otherwise you may branch from an old `main`.
- **Fresh checkout:** a new worktree has none of your gitignored files (`.env`, `node_modules`, `.venv`, `data/`).
  - A `.worktreeinclude` file at the repo root (gitignore syntax) copies listed gitignored files, such as `.env`, into every new worktree. WT-00 creates it.
  - You still need to run `make setup` in each new worktree.
- **Reopening:** running `claude --worktree <same-name>` again reopens it. To resume the conversation, use the `claude --worktree <name> --resume` command that Claude Code prints when you exit.
- **On exit:**
  - A clean worktree can be removed automatically. Named sessions ask first.
  - A worktree with changes or commits always asks before removing.
  - Manual removal: `git worktree remove .claude/worktrees/<name>`.
- **Isolation:** inside a worktree session, Claude Code blocks edits and git commands aimed at the main checkout. That protects `main`.
- **Approvals:** a "don't ask again" approval for a Bash command given in one worktree applies to all worktrees of the repo.
- **Subagents** can run in their own temporary worktrees (`isolation: worktree`). That's useful for subagents that *edit*. Those worktrees branch from the default branch, not from your worktree's `HEAD`, unless `worktree.baseRef` is `"head"`. So **review subagents should not use worktree isolation**: they only read, and they need to see your branch.

## 8.2 Golden rules

1. **Contracts first.** Nothing runs in parallel until WT-00 is merged. Contracts change only through §8.6.
2. **One worktree = one brief = one branch = one PR.** There's no "while I'm here" work. Unrelated fixes get their own small PR from `main`.
3. **Own your paths.** A worktree edits only the paths under **Owns** in its brief (§8.4). Anything else, stop and ask.
4. **`main` is always green.** Merge only when CI passes and every acceptance box is ticked with evidence.
5. **Rebase daily** onto `origin/main` while a worktree is open. Rebase again right before merging.
6. **No more than 3 active worktrees at once.** Your review attention is the bottleneck, not Claude.
7. **Decisions go in `docs/decisions/WT-NN.md`,** one dated line each: what you chose and why. Per-worktree files never conflict.
8. **Generated files are never hand-edited:** `contracts/*.json`, `web/src/lib/api/types.ts` and `docs/metrics.md`. Regenerate them with `make contracts` or `make docs`.
9. **Real numbers need a human check.** Every PR that produces financial numbers includes 2–3 values you checked against the filing yourself.

## 8.3 Waves and dependencies

```
Wave 0   WT-00 foundation  (on main — contracts, stubs, fixtures, CI)
            │
Wave 1   ┌──┴────────┬────────────┬──────────────┬──────────────┐
         WT-01        WT-02        WT-03          WT-04          WT-05
         sec-ingest   prices       normalize ★    screen-engine  web-ui
         (real SEC)   (real API)   (fixtures)     (synthetic)    (mock API)
            │            │            │               │              │
Wave 2      └─────┬──────┴─────┬──────┘               │              │
               WT-06 ★       WT-07 ★                WT-08            │
               metrics       pipeline               api              │
                  │       (merges after 06)           │              │
Wave 3            ├──────────────┬────────────────────┴──────────────┘
               WT-10          WT-09 ★ integration
               presets-method.   │
                  └───────┬──────┘
                       WT-11 ★ verify + release v0.1.0
                          │   (use it for 2 weeks)
Wave 4    WT-12 saved    WT-13 nl-screens    WT-14 history-pit    WT-15 deploy
★ = critical path
```

| WT | Name | Wave | Needs merged first | Builds against | Size |
|---|---|---|---|---|---|
| 00 | foundation | 0 | — | — | L |
| 01 | sec-ingest | 1 | 00 | Real SEC bulk files | M |
| 02 | prices | 1 | 00 | Real price provider | M |
| 03 | normalize ★ | 1 | 00 (its full-universe step waits for 01) | Committed fixtures | L |
| 04 | screen-engine | 1 | 00 | Synthetic snapshot | M |
| 05 | web-ui | 1 | 00 | Mock API (synthetic JSON) | L |
| 06 | metrics ★ | 2 | 01, 02, 03 | Real build from raw | L |
| 07 | pipeline ★ | 2 | 01, 02, 03; **merge after 06** | Stage stubs, then real stages | M |
| 08 | api | 2 | 04 | Synthetic DB, then real | M |
| 09 | integration ★ | 3 | 05, 06, 07, 08 | Real build | M |
| 10 | presets-methodology | 3 | 06 (08 for checking in the UI) | Real build | S–M |
| 11 | verify-release ★ | 3 | 09, 10 | Real build | M |
| 12 | saved-screens | 4 | 11 | — | M |
| 13 | nl-screens | 4 | 11 | — | M |
| 14 | history-pit | 4 | 11 | — | M |
| 15 | deploy-schedule | 4 | 11 | — | M |

**Suggested rounds (max 3 active):**

| Round | Worktrees |
|---|---|
| A | WT-03 ★, WT-01, WT-02 |
| B | WT-04, WT-05 (while round A finishes) |
| C | WT-06 ★, WT-07 ★, WT-08 |
| D | WT-09 ★ + WT-10, then WT-11 ★ |

## 8.4 Ownership map and hotspots

| Path | Owner | Others may… |
|---|---|---|
| `engine/glint/core/`, `engine/glint/contracts/`, `contracts/` | WT-00, then the §8.6 protocol | Read only |
| `engine/glint/ingest/sec/`, `engine/glint/universe/`, `config/sectors.yaml`, `config/sector_overrides.yaml`, `config/share_classes.yaml` | WT-01 | Read |
| `engine/glint/ingest/prices/` | WT-02 | Read |
| `engine/glint/financials/`, `config/concepts.yaml` | WT-03 | Read |
| `engine/glint/screen/` | WT-04 | Read |
| `web/` (except generated types) | WT-05, then WT-09, then 12/13/14 | — |
| `engine/glint/metrics/`, `flags/`, `quality/`, `config/thresholds.yaml`, the formula and status fields of `config/metrics.yaml` | WT-06 | WT-10 edits definition *wording* only, after 06 merges |
| `engine/glint/pipeline/`, `scripts/launchd/` | WT-07 | — |
| `engine/glint/api/` (routers) | WT-08 | WT-12/13 add their own routers |
| `engine/glint/smoke/`, `web/e2e/` (real-build specs) | WT-09 | — |
| `config/presets/*.json`, `docs/methodology.md`, `web/src/content/` | WT-10 | WT-04 commits 3 starter presets |
| `engine/tests/golden/`, `docs/release-notes.md`, `docs/known-limits.md` | WT-11 | Any worktree may *add* golden rows for its own items |
| `engine/glint/fixtures/`, `engine/tests/fixtures/` | WT-00 | Add new fixture tickers via `glint fixtures` only |

**Hotspots and how to avoid conflicts:**

| File | Rule |
|---|---|
| `engine/glint/cli.py` | WT-00 pre-registers every sub-app (`ingest`, `universe`, `financials`, `price`, `metrics`, `screen`, `refresh`, `serve`, `audit`, `smoke`, `fixtures`), each pointing at a stub module. Worktrees fill in **their own module**, never `cli.py`. |
| `engine/glint/api/app.py` | WT-00 pre-registers all routers as 501 stubs. WT-08 fills them. |
| `engine/pyproject.toml`, `uv.lock` | WT-00 pre-adds every known dependency. If you must add one, note it in the PR. On a rebase conflict, take `main`'s version, then run `uv add <dep>`, which re-locks. |
| `web/package.json`, lockfile | Only one web worktree at a time. |
| `CLAUDE.md` commands table | WT-00 lists every planned command marked *(planned)*. A worktree changes only its own rows to live. |
| `config/metrics.yaml` | Edited one worktree at a time (06, then 10). Never in parallel. |
| Generated files | On conflict, take either side, then run `make contracts` or `make docs`. |

## 8.5 Environment per worktree

| Thing | Rule |
|---|---|
| `.env` | Copied automatically by `.worktreeinclude`. Never commit it. |
| Python and Node deps | Run `make setup` once per new worktree. |
| Raw data | Shared: `GLINT_RAW_DIR=~/GlintData/raw`. Only WT-01, WT-02, WT-07 (and later pipeline runs) write there, under `raw.lock`. |
| Builds | Per worktree: `./data`. Build from shared raw with `glint refresh --no-download` (after WT-07), or with `glint fixtures synthetic` before that. |
| Ports | API `80NN`, web `30NN`, where NN is the worktree number. Example: `GLINT_API_PORT=8008 make dev-api` and `PORT=3005 make dev-web`. The main checkout uses 8000/3000. |
| DuckDB locks | One writer per file. Never point two worktrees at the same `GLINT_DB_DIR`. |

## 8.6 Contract change protocol

You'll need this when a worktree discovers that a contract (DSL, API model, enum, DB DDL, stage interface) has to change.

1. **Stop** the worktree session's work. Write down the change and why, in its decisions file.
2. In the main checkout, start a tiny worktree: `claude --worktree contract-<short-desc>`.
3. Make *only* the contract change:
   - Bump `DB_SCHEMA_VERSION` or `dsl_version` if a shape changed.
   - Run `make contracts`.
   - Update the WT-00 stubs and tests that break.
   - Add a line to `docs/decisions/CONTRACTS.md`.
4. Open a PR titled `CONTRACT: <desc>`. Wait for CI, then merge.
5. **Every** active worktree runs `git fetch origin && git rebase origin/main && make contracts && make check`.
6. Resume.

If you're changing contracts more than about once a week, the contracts were under-designed. Spend an hour on them instead of patching.

## 8.7 Lifecycle checklist (copy into every PR)

**Start**

```bash
cd ~/Claude/Glint
git switch main && git pull --ff-only
git fetch origin
claude --worktree wt03-normalize        # or: desktop app → new session → worktree option
```

- [ ] First message: paste the brief's prompt.
- [ ] Claude restates the goal, the owned paths and the acceptance criteria, and you confirm.
- [ ] Run `make setup` (Claude can run it). `.env` is present.
- [ ] In this branch, set your `docs/STATUS.md` row to 🟨 with the start date. It merges with the PR, so `main` is never edited directly.

**Build**

- [ ] Work in the brief's step order, committing `WT-03: <step>` after each one.
- [ ] Run `make check` before every commit.
- [ ] Rebase daily: `git fetch origin && git rebase origin/main`.
- [ ] If a contract change is needed, follow §8.6.

**Verify**

- [ ] Every acceptance box is ticked **with evidence**: a command plus its output, a test name, or a screenshot.
- [ ] The demo commands run, with output pasted into the PR.
- [ ] You hand-check 2–3 numbers against the filing (when the PR produces numbers).
- [ ] A review subagent runs (§8.8), and its findings are fixed in a separate `WT-03: review fixes` commit.
- [ ] `docs/decisions/WT-03.md` is updated.

**Merge**

```bash
git fetch origin && git rebase origin/main && make check
git push -u origin worktree-wt03-normalize
gh pr create --title "WT-03 normalize: FY/Q/TTM financials from XBRL" --body-file .pr.md
```

- [ ] Set your `docs/STATUS.md` row to ✅ in the PR (merged date, sessions used).
- [ ] CI is green, then **squash-merge** on GitHub.
- [ ] Other active worktrees rebase onto `origin/main`.

**Clean up**

- [ ] Exit the session (`/exit`) and choose *remove*. Or run `git worktree remove .claude/worktrees/wt03-normalize`.
- [ ] Turn on GitHub's "Automatically delete head branches" once, so remote branches tidy themselves.

## 8.8 Review protocol

Before opening the PR, say to Claude in the worktree session:

> Spawn a fresh review subagent. It only reads, so it doesn't need its own worktree; it must see this branch. Give it `docs/worktrees/WT-03-normalize.md`, `docs/SPEC.md` Part 1.5 (principles), and the output of `git diff origin/main...HEAD`. Ask it to report, most severe first: (1) acceptance criteria not met, (2) principle violations (fabricated values, missing null reasons, provider ratios, network in tests), (3) bugs, each with a concrete failure scenario, (4) missing tests. No style nits. Then fix the real findings in one commit.

You review three things yourself: the demo output, the hand-checked numbers, and the decisions file. You don't need to read every line, but you do need to read every *number*.

## 8.9 `docs/STATUS.md` template

```markdown
| WT | Name | Wave | Status | PR | Started | Merged | Sessions | Notes |
|----|------|------|--------|----|---------|--------|----------|-------|
| 00 | foundation | 0 | ⬜ | | | | | |
| 01 | sec-ingest | 1 | ⬜ | | | | | |
…
Status: ⬜ not started · 🟨 building · 🟦 in review · ✅ merged · ⛔ blocked (say on what)
```

## 8.10 The standard prompt

Every brief's prompt starts with "Follow the standard prompt". This is what it means:

```
You're in the Glint repo, worktree WT-NN (<name>).
1. Read CLAUDE.md, docs/worktrees/README.md (the rules), and your brief docs/worktrees/WT-NN-<name>.md.
2. In ≤6 lines restate: goal, paths you own, what you must not touch, acceptance criteria. Wait for my OK.
3. Edit only the paths under "Owns". If you need a contract change or another worktree's path, stop and tell me what and why.
4. Follow the brief's steps in order. Commit after each: "WT-NN: <step>". Run `make check` before every commit.
5. Record non-obvious choices in docs/decisions/WT-NN.md (one dated line: choice + why).
6. Never invent numbers, never call the network in tests, never use vendor-computed ratios.
7. When done: run the demo commands and paste output; tick every acceptance box with evidence; run the review protocol (§8.8); fix findings in a separate commit; draft the PR body as .pr.md.
```

---

# Part 9: Worktree briefs

Every brief has the same shape:

- **Header table:** wave, size, what must be merged first, worktree name, branch, ports.
- **Goal**
- **Owns:** the only paths it edits.
- **Reads / must not touch**
- **Steps**
- **Acceptance criteria:** tick each with evidence.
- **Tests**
- **Demo commands**
- **Decisions to record**
- **Gotchas**
- **Paste-in prompt**

In WT-00 each brief becomes `docs/worktrees/WT-NN-<name>.md`.
