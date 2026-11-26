"""Where to find a golden value in the filing: the facts behind Glint's number (WT-11).

    cd engine && uv run python -m tests.golden.lookup MSFT revenue [--basis fy] [--periods 3]
    cd engine && uv run python -m tests.golden.lookup --pending
    cd engine && uv run python -m tests.golden.lookup --recheck

For each of the latest periods: Glint's normalized value, the XBRL tag it came from, the
accession, form and filed date of the filing that reported it, and the filing's index URL on
EDGAR to open in a browser (nothing is fetched). Reads the committed trimmed fixtures, the same
facts `test_golden_filings.py` checks. It never writes an expected value: you take that from the
filing (principle 1).
"""

import argparse
import csv
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import orjson

from glint.contracts.enums import Basis, LineItem
from glint.financials.normalize import normalize_company
from glint.fixtures.sec import FIXTURE_DIR, fixture_name
from tests.financials.conftest import concepts, fixture_facts

GOLDEN = Path(__file__).resolve().parent / "golden_values.csv"
# Facts for golden companies outside the Appendix D fixtures (WAT, AVEX, DUOL, POWI).
EXTRA_FACT_DIRS = [Path(__file__).resolve().parents[1] / "financials" / d
                   for d in ("share_facts", "debt_facts")]  # fmt: skip


def cik_of(ticker: str) -> str:
    paths = [FIXTURE_DIR / f"{fixture_name(ticker)}.companyfacts.json"]
    paths += [d / f"{ticker}.companyfacts.json" for d in EXTRA_FACT_DIRS]
    path = next(p for p in paths if p.exists())
    return str(orjson.loads(path.read_bytes())["cik"]).zfill(10)


def filing_url(cik: str, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"


def lookup(ticker: str, item: LineItem, basis: Basis, periods: int) -> list[str]:
    facts = fixture_facts(ticker)
    forms = {f.accn: f.form for f in facts}
    cf = normalize_company(ticker, facts, concepts())
    series = cf.series(item, basis)
    cik = cik_of(ticker)
    lines = [f"{ticker} (CIK {cik}) · {item.value} · {basis.value} · reporting currency "
             f"{cf.currency}"]  # fmt: skip
    if not series:
        return [*lines, "  no value in the fixture for this item and basis"]
    for end in sorted(series, reverse=True)[:periods]:
        v = series[end]
        accn = v.source_accn or "—"
        lines += [
            f"  period_end {end}  value {v.value:,.0f} {v.unit}"
            + ("  (derived)" if v.derived else ""),
            f"    tag {v.source_tag or 'derived: ' + ', '.join(v.inputs)}",
            f"    filing {forms.get(accn, '?')} {accn}, filed {v.filed}  {filing_url(cik, accn)}",
        ]
        if v.first_filed_value is not None and v.first_filed_value != v.value:
            lines.append(f"    first filed as {v.first_filed_value:,.0f} on {v.first_filed_date} "
                         "(restated since; the golden value is the latest filed)")  # fmt: skip
    return lines


def pending_rows(path: Path = GOLDEN) -> list[dict[str, str]]:
    """Line-item rows with no value yet. A row with no value but a `where_in_filing` note is a
    deliberate null (n/m, not reported), not pending."""
    items = {li.value for li in LineItem}
    with path.open(newline="") as f:
        return [r for r in csv.DictReader(f) if r["item"] in items and not r["expected"].strip()
                and not r["where_in_filing"].strip()]  # fmt: skip


def person_verified(row: dict[str, str]) -> bool:
    """A person's name and date. A value Claude read counts only once a person confirmed it
    ("claude-chat, confirmed by NAME"; WT-11.md 2026-11-24, user decision)."""
    by = row["verified_by"].strip()
    if not (by and row["verified_on"].strip()):
        return False
    return "claude" not in by.lower() or bool(re.search(r"confirmed by \S", by))


def recheck_rows(path: Path = GOLDEN) -> list[dict[str, str]]:
    """Rows with a value no person has verified yet (blank `verified_by`, or Claude's check that no
    person confirmed)."""
    with path.open(newline="") as f:
        return [r for r in csv.DictReader(f) if r["expected"].strip() and not person_verified(r)]


def recheck_lines(row: dict[str, str]) -> list[str]:
    """The filing to open for a value already in the CSV. The value isn't printed: read the filing
    first, then compare with the CSV."""
    return [
        f"{row['ticker']} · {row['item']} · {row['basis']} · period_end {row['period_end']} "
        f"· unit {row['unit']}",
        f"    filing {row['accn']}  {filing_url(cik_of(row['ticker']), row['accn'])}",
        f"    verified_by now: {row['verified_by'] or '(nobody)'}",
    ]


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Where to find a golden value in the filing.")
    ap.add_argument("ticker", nargs="?")
    ap.add_argument("item", nargs="?", help="a line item, e.g. revenue, net_income, total_assets")
    ap.add_argument("--basis", default="fy", choices=[b.value for b in Basis])
    ap.add_argument("--periods", type=int, default=3)
    ap.add_argument("--pending", action="store_true", help="every CSV row without expected")
    ap.add_argument("--recheck", action="store_true",
                    help="every CSV row with a value no person has verified")  # fmt: skip
    a = ap.parse_args(argv)
    if a.recheck:
        rows = recheck_rows()
        _out(f"{len(rows)} golden rows have a value no person has verified yet\n")
        for r in rows:
            _out("\n".join(recheck_lines(r)) + "\n")
        return
    if a.pending:
        rows = pending_rows()
        _out(f"{len(rows)} golden rows still need a value from the filing\n")
        for r in rows:
            basis = Basis(r.get("basis") or "fy")
            out = lookup(r["ticker"], LineItem(r["item"]), basis, 1)
            _out("\n".join(out) + f"\n  → CSV row expects period_end {r['period_end']}\n")
        return
    if not a.ticker or not a.item:
        ap.error("give TICKER ITEM, or --pending")
    _out("\n".join(lookup(a.ticker.upper(), LineItem(a.item), Basis(a.basis), a.periods)))


if __name__ == "__main__":
    main()
