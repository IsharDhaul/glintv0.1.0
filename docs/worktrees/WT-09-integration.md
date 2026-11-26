# WT-09 · integration ★

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 3 | M | WT-05, WT-06, WT-07, WT-08 | `wt09-integration` | `worktree-wt09-integration` | api 8009 / web 3009 |

**Goal.** Real data end to end: a real build → API → UI, with the smoke and e2e suites, a one-command dev experience, and a README that works from a fresh clone.

**Owns.** `engine/glint/smoke/`, `web/e2e/real/`, wiring fixes in `web/src/lib/api/`, `Makefile` (`dev` target), `README.md`, `docs/decisions/WT-09.md`.

**Must not touch.** Metric formulas, the financials logic or contracts. Log bugs found there as tiny separate PRs from `main`, or use the protocol.

**Steps**

1. **Real build.** Run `glint refresh` (or `--no-download` from shared raw). Then run `glint audit` and skim the results.
2. **Wire the UI to the real API.** Set `NEXT_PUBLIC_GLINT_MOCK=0`. Fix any shape or behaviour mismatches without changing components' contracts.
3. **`make dev`.** Starts the API and the web together (ports from env), with one Ctrl-C to stop both.
4. **`glint smoke`.**
   - Runs every preset and checks: no errors, a total within [1, 2000], and sieve counts that never increase.
   - Looks up every Appendix D company and checks: 200 response, expected kinds and n/m codes.
   - Checks search cases.
   - Exits non-zero on any failure.
5. **Real-build e2e** (Playwright, local only, not CI): run a preset → open the drawer → the source link points at sec.gov → export CSV → reload the share URL.
6. **Performance on real data.** Re-measure the §5.10 budgets against the real build and record them.
7. **README quickstart.** Clone → `.env` → `make setup` → `glint ingest sec` → `glint ingest prices --backfill 300` → `glint refresh` → `make dev`, with honest timings.
8. **Known issues.** Write `docs/known-limits.md` for anything deferred.

**Acceptance criteria**

- [ ] `glint smoke` passes.
- [ ] The real-build e2e passes locally, with a screenshot of the real screener (dated) in the PR.
- [ ] The §5.10 budgets are met on real data, or there's a decision recorded with a follow-up.
- [ ] Fresh-clone test: following the README in a new worktree gives a working app. Data download time is excluded, and every step is noted.
- [ ] The mock banner never appears in real mode, and the real as-of stamps show.

**Demo:** `make dev` with screenshots, plus `glint smoke` output.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-09 (integration).
Your brief: docs/worktrees/WT-09-integration.md. Spec context: docs/SPEC.md §1.7, §5.8, §5.10.
You may not change metric formulas, financials logic, or contracts here — list any bugs you find and I'll open separate PRs.
```
