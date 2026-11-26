# WT-00 · foundation ★

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 0 | L | — | `wt00-foundation` | `worktree-wt00-foundation` | 8000 / 3000 |

**Goal.** Build the skeleton that makes every later worktree independent: repo, tooling, CI, docs, the SEC gateway, **all contracts**, pre-wired CLI and API stubs, real fixtures and synthetic data. After this merges, five worktrees can start at once without touching shared files.

**Step 0 (you, in Terminal, before Claude):**

```bash
mkdir -p ~/Claude/Glint && cd ~/Claude/Glint
git init -b main
mv ~/Downloads/stock-screener-plan.md .        # this file
git add . && git commit -m "Plan"
gh repo create glint --private --source=. --push
claude                                          # accept the workspace-trust prompt once, then /exit
git fetch origin
claude --worktree wt00-foundation
```

**Owns.** Everything except the module bodies that later worktrees fill in. In practice: the repo root files, `.github/`, `config/` (initial versions), `contracts/`, `engine/glint/{core,contracts,fixtures}/`, `engine/glint/cli.py`, `engine/glint/api/app.py` plus router stubs, stub `__init__.py` modules for every package, `engine/tests/fixtures/`, the `web/` scaffold and `docs/`.

**Steps**

1. **Repo hygiene.**
   - `.gitignore`: `data/`, `.env*` (but not `.env.example`), `.venv/`, `node_modules/`, `web/.next/`, `.claude/worktrees/`, `*.duckdb`, `.pr.md`.
   - `.worktreeinclude`: `.env` and `web/.env.local`.
   - `.env.example`: exactly as in §5.6.
2. **Docs.**
   - Split this plan into files:
     - Parts 1–7 → `docs/SPEC.md`
     - Part 8 → `docs/worktrees/README.md`
     - Each Part 9 brief → `docs/worktrees/WT-NN-<name>.md`
     - Appendix A → `CLAUDE.md`
   - Create `docs/DESIGN.md` from §3.4, marked *proposal*.
   - Create `docs/STATUS.md` (§8.9) with every row ⬜.
   - Create `docs/decisions/README.md` and `docs/decisions/CONTRACTS.md`.
   - Write `README.md` with a quickstart (setup, check, dev).
   - Delete the root `stock-screener-plan.md` in the same commit, so the split files are the single source of truth.
3. **Engine scaffold** (`engine/`):
   - Create the `uv` project (Python ≥ 3.12, package `glint`).
   - Add every dependency from §5.1 now (duckdb, polars, pydantic, pydantic-settings, httpx, tenacity, aiolimiter, orjson, typer, rich, fastapi, uvicorn, rapidfuzz, pyyaml, yfinance). Dev deps: pytest, pyright, ruff.
   - Configure ruff (line length 100, sensible rules) and pyright strict.
   - Configure pytest markers: `live`, `slow`.
4. **Core** (`glint/core/`):
   - `settings.py`: pydantic-settings, reading `.env`, with `~` expanded.
   - `paths.py`: raw, db, builds, current pointer, user db.
   - `errors.py`: `GlintError`, `SourceError`, `NotCoveredError`, `ContractError`.
   - `log.py`: structured logging.
   - `filelock.py`: an exclusive lock on `GLINT_RAW_DIR/raw.lock`.
   - `http.py`: the SEC gateway. It sets the User-Agent from settings, limits rate with `aiolimiter` (`GLINT_SEC_MAX_RPS`), retries with tenacity on 429/5xx/network errors (exponential backoff with jitter), supports conditional GET (ETag and Last-Modified stored next to the file), and streams large downloads to disk. **Nothing else may call SEC.**
   - `cache.py`: a JSON file cache with TTLs and schema-versioned keys (`sec:companyfacts:v1:<cik>`), used by fixtures and dev lookups.
5. **Contracts** (`glint/contracts/`), exactly as specified in Parts 2, 4 and 5:
   - `enums.py`: `LineItem` (every item in Appendix B), `Sector` (Appendix C list), `Kind`, `NoteCode` (§2.4), `Unit`, `Basis`, `Tier`, `Category`.
   - `metrics.py`: a `MetricDefinition` model (id, name, category, unit, better, tier, priority, basis, definition, inputs, applicability, status `planned|live`).
   - `screen.py`: the Screen DSL with every validation rule in §5.4. Validation that needs the registry takes the registry as an argument.
   - `api.py`: request and response models for every endpoint in §5.5, including v1/v2 models (marked so).
   - `db.py`: DDL for every table in §4.7, plus `DB_SCHEMA_VERSION = 1`.
   - `pipeline.py`: `BuildContext`, `Stage` (protocol: `name`, `deps`, `run(ctx) -> StageResult`), and `StageResult` (counts, warnings, duration).
6. **Registries** (`config/`):
   - `metrics.yaml`: **every** metric in §2.4 with full metadata, `status: planned`.
   - `concepts.yaml`: Appendix B.
   - `sectors.yaml`: Appendix C.
   - `thresholds.yaml`: flag thresholds (§2.10), audit rules (§4.6), freshness limits, tolerance `1e-9`.
   - Empty `sector_overrides.yaml` and `share_classes.yaml`, each with a comment header.
   - `presets/README.md`.
   - A test checks that `metrics.yaml` parses into `MetricDefinition` and that every id is unique and snake_case.
7. **CLI skeleton.** In `glint/cli.py`, register every sub-app: `fixtures`, `ingest`, `universe`, `price`, `financials`, `metrics`, `screen`, `refresh`, `serve`, `audit`, `smoke`. Each lives in its own module and prints `not implemented yet (WT-NN)` with exit code 2.
8. **API skeleton.**
   - `glint/api/app.py` is a factory that registers routers for every §5.5 path, returning 501 with `{error:"NOT_IMPLEMENTED"}`.
   - `/api/health` and `/api/meta` really work: `meta` reads `data/current.json` if it exists.
   - Add `scripts/export_openapi.py`, which writes `contracts/openapi.json` and `contracts/screen.schema.json`.
9. **Web scaffold** (`web/`):
   - Next.js App Router with TypeScript strict and `noUncheckedIndexedAccess`.
   - Tailwind with CSS-variable tokens from §3.4, ESLint flat config, Vitest and Playwright.
   - `openapi-typescript` generates `src/lib/api/types.ts`.
   - One placeholder page showing `/api/meta`.
10. **Fixtures (real).** Implement `glint fixtures sec`:
    - For each ticker in Appendix D, fetch companyfacts and submissions through the gateway.
    - Trim to the tags in `concepts.yaml` plus dei cover tags.
    - Write `engine/tests/fixtures/sec/<TICKER>.companyfacts.json` and `<TICKER>.submissions.json`.
    - Also save a trimmed `company_tickers_exchange.json`.
    - Choose the SPAC, recent-IPO and FY-change examples at runtime from submissions, and record which you picked in `docs/decisions/WT-00.md`.
    - Keep the total fixture size under 25 MB.
11. **Fixtures (synthetic).** Implement `glint fixtures synthetic --n 6000 --seed 7`:
    - Build `data/builds/synthetic.duckdb` with `companies` and `metrics_snapshot` (+ `metric_notes`, `metric_history`, `flags`) matching `db.py`.
    - Tickers are `SYN0001…`, names are "Synthetic Co 0001", sectors are spread realistically, and values are plausible (sector-shaped distributions) with about 10% nulls carrying valid reason codes.
    - Write `data/current.json` pointing at it.
    - Export `web/mocks/{meta,metrics,companies}.json`.
    - **Synthetic data must be impossible to mistake for real data.** Every row has `kind="synthetic"`, and `meta.synthetic=true`.
12. **Make targets.**

    | Target | Does |
    |---|---|
    | `setup` | uv sync + npm ci |
    | `check` | lint, typecheck and tests for both |
    | `test` | Tests only |
    | `contracts` | Export OpenAPI and schema, then regenerate TS types |
    | `docs` | Generate `docs/metrics.md` from the registry |
    | `dev-api` | Runs on `${GLINT_API_PORT:-8000}` |
    | `dev-web` | Runs on `${PORT:-3000}` |
    | `fixtures` | Rebuild fixtures |
    | `synthetic` | Rebuild synthetic data |

13. **CI.** `.github/workflows/ci.yml` with the three jobs from §5.9.
14. **Docs check.** Make sure `CLAUDE.md`'s commands table lists every command, with *(planned)* where it isn't built yet.

**Acceptance criteria**

- [ ] `make setup && make check` passes locally. CI is green on the PR.
- [ ] `uv run glint --help` lists all 11 sub-apps. Each stub exits with code 2 and names its worktree.
- [ ] `make contracts` produces no diff after a clean checkout.
- [ ] `config/metrics.yaml` loads; every §2.4 metric is present with `status: planned`.
- [ ] Real fixtures exist for every Appendix D ticker, under 25 MB in total, and the picks are recorded in the decisions file.
- [ ] `glint fixtures synthetic` builds a 6,000-row DB, and `/api/meta` reports `synthetic: true`.
- [ ] `/api/health` returns 200. Every other route returns 501 with the error model.
- [ ] `.worktreeinclude` works: `claude --worktree test-include` contains `.env`. Remove that worktree afterwards.
- [ ] `docs/worktrees/` has 16 briefs plus `README.md`. `docs/STATUS.md` exists.
- [ ] No network calls in tests. Running `pytest` with Wi-Fi off passes.

**Demo commands:** `uv run glint --help` · `uv run glint fixtures synthetic` · `make dev-api` then `curl localhost:8000/api/meta`.

**Decisions to record:** fixture picks; the Python version; ruff rule set; any contract field you added that the plan didn't specify (with the reason).

**Gotchas**

- The SEC wants a real contact in the User-Agent. Use your own email in `.env`, never in committed files.
- Don't implement real logic in stubs. Later worktrees own it.
- Keep the generated files out of hand edits from day one.

**Paste-in prompt**

```
You're in the Glint repo, worktree WT-00 (foundation). The full plan is stock-screener-plan.md at the repo root.
Read Part 1.5 (principles), Part 5 (architecture), Part 8 (playbook), and the WT-00 brief in Part 9.
In ≤6 lines restate: goal, what you'll create, acceptance criteria. Wait for my OK.
Then do the 14 steps in order, committing "WT-00: <step>" after each and running `make check` before each commit (from step 3 on).
Contracts must match the plan exactly; if the plan is ambiguous, pick the simplest option and log it in docs/decisions/WT-00.md.
Never invent financial numbers; synthetic data must be unmistakably synthetic.
When done: paste demo output, tick each acceptance box with evidence, run a fresh review subagent on `git diff origin/main...HEAD` against this brief, fix findings in a separate commit, and draft .pr.md.
```
