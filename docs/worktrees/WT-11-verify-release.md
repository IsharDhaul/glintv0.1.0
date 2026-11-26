# WT-11 · verify-release ★

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 3 | M | WT-09, WT-10 | `wt11-verify-release` | `worktree-wt11-verify-release` | api 8011 / web 3011 |

**Goal.** Prove the numbers are right, close the MVP and tag `v0.1.0`. This is the worktree where you personally do the most work.

**Owns.** `engine/tests/golden/`, `docs/release-notes.md`, `docs/known-limits.md` (append), `docs/decisions/WT-11.md`. Small fix PRs go to their owning areas *as separate PRs*.

**Steps**

1. **Golden set (you).** Bring the total to **30 golden values**:
   - 10 companies (mix sectors, FY ends, one foreign) × 3 items, taken straight from the filings.
   - Columns: `ticker, item, basis, period_end, expected, unit, accn, where_in_filing, verified_by, verified_on`.
   - The tests compare at 0.5% tolerance.
2. **Metric spot-check (you + Claude).** 20 more metric values recomputed by hand in a spreadsheet from the golden inputs. Disagreements get investigated with `--explain` before anything changes.
3. **Universe review.** Read `glint audit` and the coverage report. Every remaining outlier class is explained in `known-limits.md`.
4. **Full review.** A fresh review subagent reviews the whole repo against `docs/SPEC.md` §1.5 and §1.7, most severe first. Fixes go to their owners as small PRs.
5. **§1.7 checklist.** Tick each item with evidence in `docs/release-notes.md`.
6. **Use it for real.** Run 3 screens for an actual Nexus idea session and write down what was missing or confusing. That's your v1 priority list.
7. **Tag** `v0.1.0`, and push the tag.

**Acceptance criteria**

- [ ] 30 golden values pass, and 20 spot-checks agree or are explained.
- [ ] Every §1.7 criterion is ticked with evidence.
- [ ] No open P0 bugs. `known-limits.md` is honest and current.
- [ ] Release notes include the real numbers: universe size, coverage, timings and budgets.
- [ ] The v1 priority list from real use is recorded.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-11 (verify-release).
Your brief: docs/worktrees/WT-11-verify-release.md. Spec context: docs/SPEC.md §1.5, §1.7, §5.8.
I will enter golden values from the filings myself — set up the CSV, the test, and a helper that prints the exact facts (tag, period, accession) for any ticker/item so I can find them in the filing quickly. Never fill in expected values yourself.
```
