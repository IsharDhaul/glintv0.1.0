# WT-14 · history-pit

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 4 | M | WT-11 | `wt14-history-pit` | `worktree-wt14-history-pit` | api 8014 / web 3014 |

**Goal.** Make history useful (metric charts, plus "what did this screen return on date X" from archived snapshots) and decide, with evidence, whether a credible backtest is possible.

**Owns.** `engine/glint/history/` (new), the history router, history UI components, `docs/research/point-in-time.md`, `docs/decisions/WT-14.md`.

**Steps**

1. **Metric history charts** in the drawer and company page, for FY and TTM, with period labels and source tooltips.
2. **Snapshot browser.** Pick an archived date and run any screen against *that* snapshot. The UI says plainly which build and date it's using.
3. **Research spike** (a document, not a feature): could Glint rebuild point-in-time fundamentals from the `filed` dates in companyfacts?
   - What it would take to include delisted companies: a CIK history, a ticker history, a price source covering delisted names.
   - Cost, effort and the biases that would remain.
   - Conclusion: build, defer, or never.
4. **No performance numbers anywhere in the UI** from this work unless the research doc concludes "build" and you approve a separate brief.

**Acceptance criteria**

- [ ] Running a screen on an archived date works and is clearly labelled.
- [ ] The research doc exists, with a recommendation and the evidence behind it.
- [ ] A grep test confirms no returns or performance language was added to the UI.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-14 (history-pit).
Your brief: docs/worktrees/WT-14-history-pit.md. Spec context: docs/SPEC.md §2.15, §4.3 rule 3, §1.5.
Step 3 is research: write docs/research/point-in-time.md and stop for my decision before building anything backtest-shaped.
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
