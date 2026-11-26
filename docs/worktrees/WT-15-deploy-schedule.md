# WT-15 · deploy-schedule

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 4 | M | WT-11 | `wt15-deploy-schedule` | `worktree-wt15-deploy-schedule` | — |

**Goal.** Decide how Glint runs day to day (local and scheduled, or hosted for Nexus), then implement that choice safely.

**Owns.** `deploy/` (new), `scripts/launchd/` (finalize), CI deploy workflow (new file), `docs/deploy.md`, `docs/decisions/WT-15.md`.

**Steps**

1. **Decision doc first.** Compare:
   - **(a)** local with launchd (free, private, only you)
   - **(b)** API and DuckDB on a small VM or app host with a persistent volume, plus the web on a static/edge host
   - **(c)** a read-only static export of the latest snapshot (cheapest way to share)

   Cover cost per month, upkeep, auth needs, and **data licensing**: can you show price-derived data to other Nexus members under your price provider's plan? Read the terms and quote them.
2. **Implement the chosen option.**
   - If hosted: auth (at least a shared password, or proper accounts for Nexus), HTTPS, the refresh job scheduled on the host, backups of `user.duckdb`, and log retention.
   - If local: install the launchd job, with log rotation and a failure notification (macOS notification).
3. **Runbook:** how to deploy, roll back, rotate keys and restore user data.

**Acceptance criteria**

- [ ] You approve the decision doc before implementation.
- [ ] Licensing is checked and quoted, and the choice complies.
- [ ] Scheduled refreshes run for 7 days without manual help (logs attached).
- [ ] A restore from backup is tested.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-15 (deploy-schedule).
Your brief: docs/worktrees/WT-15-deploy-schedule.md. Spec context: docs/SPEC.md §4.8, §4.9, §1.5 rule 9.
Step 1 is a decision doc — research current hosting prices and the price provider's display/redistribution terms, cite sources, and stop for my decision.
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
