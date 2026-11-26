"""WT-11 metric spot-checks: 20 FY metric values to recompute by hand from the filings.

    cd engine && uv run python -m tests.golden.spotcheck --write   # (re)write spot_checks.csv

For each pick: Glint's FY history value, the metric's definition, and every input Glint used
(value, period, XBRL tag, accession), so the value can be rebuilt in a spreadsheet from the 10-K.
`your_value`, `verified_by`, `verified_on` and `note` are left blank for the person checking;
`--write` keeps whatever they already entered. A disagreement is investigated with
`glint metrics TICKER --explain ID` before anything changes (brief step 2).
"""

import argparse
import csv
import sys
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from glint.contracts.metrics import MetricRegistry, load_registry
from tests.golden.fixture_build import build

SHEET = Path(__file__).resolve().parent / "spot_checks.csv"
COLUMNS = ["ticker", "metric_id", "basis", "period_end", "glint_value", "definition", "inputs",
           "your_value", "verified_by", "verified_on", "note"]  # fmt: skip
GOLDEN_FY = {
    "MSFT": "2026-06-30", "JPM": "2025-12-31", "MU": "2026-09-03", "SBUX": "2025-09-28",
    "O": "2025-12-31", "KHC": "2025-12-27", "GOOGL": "2025-12-31", "RIVN": "2025-12-31",
    "BRK.B": "2025-12-31", "TSM": "2024-12-31",
}  # fmt: skip
PICKS = [  # 20; KHC's other FY metrics are already golden rows
    ("MSFT", "operating_margin"), ("MSFT", "roic"), ("MSFT", "fcf_margin"),
    ("JPM", "revenue_growth_yoy"), ("JPM", "share_count_change_yoy"),
    ("MU", "revenue_growth_yoy"), ("MU", "gross_margin"),
    ("SBUX", "operating_margin"), ("SBUX", "net_debt_to_ebitda"),
    ("O", "revenue_growth_yoy"), ("O", "share_count_change_yoy"),
    ("KHC", "share_count_change_yoy"),
    ("GOOGL", "fcf_margin"), ("GOOGL", "net_debt_to_ebitda"),
    ("RIVN", "gross_margin"), ("RIVN", "roic"),
    ("BRK.B", "revenue_growth_yoy"), ("BRK.B", "fcf_margin"),
    ("TSM", "gross_margin"), ("TSM", "roic"),
]  # fmt: skip
INPUTS = {  # line items behind each FY history metric (glint/metrics/history.py)
    "gross_margin": ["revenue", "gross_profit", "cost_of_revenue"],
    "operating_margin": ["revenue", "operating_income"],
    "fcf_margin": ["revenue", "fcf", "cfo", "capex"],
    "revenue_growth_yoy": ["revenue"],
    "roic": ["operating_income", "pretax_income", "income_tax", "total_debt", "equity",
             "minority_interest", "cash", "st_investments"],
    "net_debt_to_ebitda": ["total_debt", "cash", "st_investments", "operating_income", "dna",
                           "ebitda"],
    "share_count_change_yoy": ["diluted_shares"],
}  # fmt: skip
PRIOR_YEAR = {"revenue_growth_yoy", "roic", "share_count_change_yoy"}  # also need the year before


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.6g}"


def _inputs(fin: pl.DataFrame, cik: str, metric_id: str, end: date) -> str:
    fy = fin.filter((pl.col("cik") == cik) & (pl.col("basis") == "fy"))
    ends = sorted({e for e in fy["period_end"].to_list() if e <= end}, reverse=True)
    wanted = ends[:2] if metric_id in PRIOR_YEAR else ends[:1]
    rows = fy.filter(
        pl.col("line_item").is_in(INPUTS[metric_id]) & pl.col("period_end").is_in(wanted)
    ).sort("period_end", "line_item", descending=[True, False])
    parts = [
        f"{r['line_item']} {r['period_end']} = {_fmt(r['value'])} {r['unit']} "
        f"[{r['source_tag'] or 'derived'} · {r['source_accn']}]"
        for r in rows.iter_rows(named=True)
    ]
    return "; ".join(parts)


def _definition(reg: MetricRegistry, metric_id: str) -> str:
    m = reg.get(metric_id)
    if m is None:
        raise KeyError(f"{metric_id} is not in the metric registry")
    return m.definition


def sheet_rows(folder: Path) -> list[dict[str, str]]:
    """The 20 picks with Glint's current values and inputs (no person-entered columns)."""
    out, fin = build(folder)
    reg = load_registry()
    rows: list[dict[str, str]] = []
    for ticker, metric_id in PICKS:
        end = date.fromisoformat(GOLDEN_FY[ticker])
        cik = out.frame.filter(pl.col("tickers").list.contains(ticker))["cik"][0]
        hit = out.history.filter(
            (pl.col("cik") == cik) & (pl.col("metric_id") == metric_id)
            & (pl.col("basis") == "fy") & (pl.col("period_end") == end)
        )  # fmt: skip
        value = "" if hit.is_empty() else repr(float(hit["value"][0]))
        rows.append({
            "ticker": ticker, "metric_id": metric_id, "basis": "fy", "period_end": str(end),
            "glint_value": value, "definition": _definition(reg, metric_id),
            "inputs": _inputs(fin, cik, metric_id, end),
        })  # fmt: skip
    return rows


def read_sheet(path: Path = SHEET) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_sheet(rows: list[dict[str, str]], path: Path = SHEET) -> None:
    """Writes Glint's columns; keeps what the checker entered for the same ticker and metric."""
    kept = {(r["ticker"], r["metric_id"]): r for r in read_sheet(path)}
    person = ("your_value", "verified_by", "verified_on", "note")
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            old = kept.get((r["ticker"], r["metric_id"]), {})
            w.writerow({**r, **{k: old.get(k, "") for k in person}})


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="WT-11 metric spot-check sheet.")
    ap.add_argument("--write", action="store_true", help=f"(re)write {SHEET.name}")
    a = ap.parse_args(argv)
    rows = sheet_rows(Path(tempfile.mkdtemp(prefix="glint-spot-")) / "2026-10-29")
    if a.write:
        write_sheet(rows)
        sys.stdout.write(f"wrote {len(rows)} rows to {SHEET}\n")
        return
    for r in rows:
        sys.stdout.write(f"{r['ticker']} {r['metric_id']} {r['period_end']}: {r['glint_value']}\n"
                         f"  {r['inputs']}\n")  # fmt: skip


if __name__ == "__main__":
    main()
