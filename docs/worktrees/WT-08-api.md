# WT-08 · api

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 2 | M | WT-04 | `wt08-api` | `worktree-wt08-api` | api 8008 |

**Goal.** A FastAPI service exposing every §5.5 endpoint over the current build (synthetic or real), meeting the performance budgets, with contracts and generated TypeScript types in sync.

**Owns.** `engine/glint/api/` (router bodies), `engine/tests/api/`, regenerated `contracts/openapi.json`, `docs/decisions/WT-08.md`.

**Must not touch.** Request and response *models* (contracts; use the protocol), the screen engine internals, the web.

**Steps**

1. **Build access.**
   - Open a read-only DuckDB connection to the build in `current.json`.
   - Check the pointer's mtime at most every 30 s and reconnect on change.
   - Refuse with 503 `SCHEMA_MISMATCH` if the `DB_SCHEMA_VERSION` differs, or `NO_BUILD` if there isn't one.
2. **Endpoints**, in this order: `meta`, `metrics`, `sectors`, `presets`, `screen` (calls WT-04's engine), `distribution`, `search`, `companies`, `history`, `export`.
3. **Search:** exact ticker → ticker prefix → name prefix → rapidfuzz on name, with 10 results max, so "appel" finds AAPL.
4. **Company endpoint:** snapshot, notes, flags, history, sources (accession → SEC URL), and why-passed when `?screen=` (compressed) is supplied.
5. **Export:** stream CSV with the §2.12 columns and filename.
6. **Errors:** the §5.5 error model, `build_id` on every response, and structured request logs (path, ms, build).
7. **CORS** for `localhost:3000–3099` only.
8. **`glint serve`.** Runs uvicorn on `GLINT_API_PORT` with reload in dev.
9. **Contracts.** Run `make contracts`. Response-validation tests check that every endpoint's output validates against OpenAPI, using FastAPI's TestClient on the synthetic build.
10. **Performance.** A timing test for `/api/screen` with 10 filters and near misses on the 6,000-row synthetic build: p95 < 300 ms end to end. `companies` p95 < 150 ms.

**Acceptance criteria**

- [ ] Every §5.5 MVP endpoint is implemented, and v1/v2 routes still return 501.
- [ ] Contract tests pass, and `make contracts` produces no diff.
- [ ] The performance budgets are met and the numbers recorded.
- [ ] "appel" → AAPL, "brk b" → BRK.B and "googl" → GOOGL all work (on synthetic data, use equivalent SYN cases; repeat on the real build in WT-09).
- [ ] With no build, you get 503 `NO_BUILD` and a helpful message. A schema mismatch gives 503 `SCHEMA_MISMATCH`.
- [ ] Swapping `current.json` while the server runs picks up the new build within 30 s, with no restart.

**Demo commands:** `GLINT_API_PORT=8008 glint serve` · `curl -s localhost:8008/api/meta | jq` · `jq '.screen' config/presets/magic-formula.json | curl -s -X POST localhost:8008/api/screen -H 'content-type: application/json' -d @- | jq '.funnel'`.

**Gotchas**

- Presets are stored with metadata around the screen. The `/api/screen` body is the `screen` object only. Be consistent, and document it.
- Don't cache screen results across builds. Key any cache by `build_id`.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-08 (api).
Your brief: docs/worktrees/WT-08-api.md. Spec context: docs/SPEC.md §5.5, §5.7, §5.10, §2.9, §2.12.
Develop against the synthetic build on port 8008. Models are contracts — if one is wrong, stop and tell me (contract protocol §8.6).
```
