"""Generate docs/metrics.md from config/metrics.yaml (run via `make docs`)."""

import sys

from glint.contracts.enums import Better, Category
from glint.contracts.metrics import MetricDefinition, load_registry
from glint.core.settings import REPO_ROOT

COLUMNS = (
    "id",
    "Name",
    "Definition",
    "Inputs",
    "Unit",
    "Better",
    "Tier",
    "Basis",
    "P",
    "n/m for",
    "Status",
)
ARROWS = {Better.HIGHER: "↑", Better.LOWER: "↓", Better.NEUTRAL: "·"}
TITLES = {
    Category.SIZE_LIQUIDITY: "Size and liquidity",
    Category.VALUATION: "Valuation",
    Category.PROFITABILITY: "Profitability and returns",
    Category.GROWTH: "Growth",
    Category.BALANCE_SHEET: "Balance sheet and health",
    Category.EFFICIENCY: "Efficiency and reinvestment",
    Category.QUALITY: "Quality and accounting",
    Category.PRICE_MOMENTUM: "Price and momentum",
    Category.DATA_QUALITY: "Data quality",
}


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def definition_cell(m: MetricDefinition) -> str:
    """The definition, plus tells_you / misleads when the registry provides them."""
    parts = [cell(m.definition)]
    if m.tells_you:
        parts.append(f"**Tells you:** {cell(m.tells_you)}")
    if m.misleads:
        parts.append(f"**Misleads when:** {cell(m.misleads)}")
    return "<br>".join(parts)


def main() -> int:
    reg = load_registry()
    lines = [
        "# Metric dictionary",
        "",
        "<!-- GENERATED from config/metrics.yaml by `make docs`. Do not edit by hand. -->",
        "",
        "Units: `usd` · `frac` (0.15 = 15.0%) · `pp` (percentage points, stored as a fraction) · "
        "`x` (multiple) · `days` · `score` · `bool`. Better: ↑ higher · ↓ lower · · neutral.",
        "",
    ]
    for category in Category:
        metrics = [m for m in reg if m.category is category]
        if not metrics:
            continue
        lines += [
            f"## {TITLES[category]}",
            "",
            "| " + " | ".join(COLUMNS) + " |",
            "|" + "---|" * len(COLUMNS),
        ]
        for m in metrics:
            nm = ", ".join(s.value for s in m.applicability.not_meaningful) or "—"
            lines.append(
                f"| `{m.id}` | {cell(m.name)} | {definition_cell(m)} | {', '.join(m.inputs)} "
                f"| {m.unit.value} | {ARROWS[m.better]} | {m.tier.value} | {m.basis.value} "
                f"| {m.priority.value} | {nm} | {m.status.value} |"
            )
        lines.append("")
    out = REPO_ROOT / "docs" / "metrics.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out} ({len(reg)} metrics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
