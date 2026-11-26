# Presets

One JSON file per preset, named `<id>.json` (SPEC §2.8). Shape (`glint.contracts.api.Preset`, minus `id`):

```json
{
  "name": "Magic Formula",
  "summary": "One line on what it finds.",
  "kind": "screen",
  "how_to_read": "What the screen looks for and how to read a match.",
  "misses": ["One short line per known blind spot."],
  "source": "Greenblatt, The Little Book That Beats the Market (2005)",
  "screen": { "dsl_version": 1, "...": "a Screen (contracts/screen.schema.json)" }
}
```

Rules:

- `kind` is required: `screen`, or `red_flags` for a risk screen (each match is a question, not a buy idea).
- `misses` is optional (default `[]`): what the screen can't see, one plain-language line each.
- Presets may use only **P0** metrics.
- Thresholds are starting points; WT-10 tunes them on real data so each returns a workable list.
- Presets never claim returns.
- WT-04 commits the first three (`magic-formula`, `quality-compounders`, `dilution-watch`); WT-10 owns the rest.
