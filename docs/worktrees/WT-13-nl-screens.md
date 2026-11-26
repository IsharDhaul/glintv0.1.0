# WT-13 · nl-screens

| Wave | Size | Needs merged | Worktree | Branch | Ports |
|---|---|---|---|---|---|
| 4 | M | WT-11 | `wt13-nl-screens` | `worktree-wt13-nl-screens` | api 8013 / web 3013 |

**Goal.** Type a screen in plain English and get a **draft** Screen JSON shown as editable chips. It runs only when you press Apply. Claude never supplies company numbers.

**Owns.** `engine/glint/nl/` (new), `engine/glint/api/routers/nl.py`, the NL input component in `web/`, `engine/tests/nl/`, `evals/nl/`, `docs/decisions/WT-13.md`.

**Steps**

1. **Prompt.** Use the `anthropic` SDK, with the model from `GLINT_LLM_MODEL`. The system prompt contains the live metric registry (ids, names, units, definitions), the comparators, the unit rule ("percent → fraction") and the universe options. It contains **no company data**.
2. **Output.** Claude returns Screen JSON via structured output or tool use, validated with the same validator as WT-04, with one retry carrying the validation errors, then a clear failure message.
3. **Explanation.** Show a short "how I read your request" note beside the chips, and flag any phrase it couldn't map (for example "great management → no metric for this").
4. **Eval set.** `evals/nl/cases.yaml` holds 40 prompts with the expected filters (metric, comparator and value range). `make eval-nl` runs them manually (not in CI; it costs API calls) and prints the pass rate. Target ≥ 90%.
5. **Feature flag.** The UI hides the input when there's no `ANTHROPIC_API_KEY`. Log latency and token use per request.

**Acceptance criteria**

- [ ] Eval pass rate is ≥ 90% (recorded), and all unit-conversion cases pass.
- [ ] Unknown concepts are reported, never silently dropped or invented.
- [ ] A test proves no company values are sent to the model (inspect the request payload).
- [ ] Nothing runs before you press Apply.

**Paste-in prompt**

```
Follow the standard prompt in docs/worktrees/README.md §8.10 for WT-13 (nl-screens).
Your brief: docs/worktrees/WT-13-nl-screens.md. Spec context: docs/SPEC.md §2.13, §5.4, §1.5 rules 1 and 3.
Before writing code, check the current Anthropic SDK docs for structured outputs / tool use and record the approach in docs/decisions/WT-13.md. The model only translates intent into the DSL; it never sees or produces company numbers.
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
