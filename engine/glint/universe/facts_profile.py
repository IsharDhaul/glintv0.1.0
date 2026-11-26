"""Per-company facts profile from facts_raw (WT-01 step 5): has_facts, taxonomy, currency.

- has_facts: the CIK has at least one us-gaap or ifrs-full fact in facts_raw (whitelisted tags).
- taxonomy: whichever of us-gaap / ifrs-full holds more revenue facts (ties → us-gaap).
- reporting_currency: the most common ISO currency unit on revenue facts in that taxonomy.
Revenue tags come from concepts.yaml's `revenue` line item. A company with financial facts but no
revenue facts (pre-revenue, or revenue under an untracked tag) falls back to all its monetary
facts; `basis` says which was used.

Equity evidence (for kind `no_common_equity`, see classify.py): the largest undimensioned
cover-page `dei:EntityCommonStockSharesOutstanding` in each filing, and the latest period end of a
per-share fact (concepts.yaml `eps_diluted` / `diluted_shares` tags). Companies with listed common
stock must report EPS; issuers whose only listed securities are debt or preferreds needn't.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import duckdb
import yaml

from glint.core.settings import REPO_ROOT

CONCEPTS_PATH = REPO_ROOT / "config" / "concepts.yaml"
Basis = Literal["revenue", "all facts"]


@dataclass(frozen=True)
class FactsProfile:
    has_facts: bool
    taxonomy: str | None
    reporting_currency: str | None
    basis: Basis | None = None


def line_item_tags(*items: str, concepts_path: Path = CONCEPTS_PATH) -> list[tuple[str, str]]:
    doc: dict[str, Any] = yaml.safe_load(concepts_path.read_text())
    out: list[tuple[str, str]] = []
    for item in items:
        tags: dict[str, list[str]] = doc["line_items"][item]["tags"]
        out += [(tax, tag) for tax, names in tags.items() for tag in names]
    return out


def revenue_tags(concepts_path: Path = CONCEPTS_PATH) -> list[tuple[str, str]]:
    return line_item_tags("revenue", concepts_path=concepts_path)


PER_SHARE_ITEMS = ("eps_diluted", "diluted_shares")


@dataclass(frozen=True)
class EquityEvidence:
    # accession → largest undimensioned cover-page share count in that filing
    cover_by_accn: dict[str, float] = field(default_factory=dict[str, float])
    last_per_share_end: date | None = None  # latest period end of a diluted EPS / share fact

    def merged(self, other: "EquityEvidence | None") -> "EquityEvidence":
        """This company's evidence plus a predecessor CIK's (whose filings it may inherit)."""
        if other is None:
            return self
        ends = [d for d in (self.last_per_share_end, other.last_per_share_end) if d is not None]
        return EquityEvidence(
            {**other.cover_by_accn, **self.cover_by_accn}, max(ends) if ends else None
        )


def equity_evidence(facts_dir: Path, per_share: list[tuple[str, str]]) -> dict[str, EquityEvidence]:
    if not any(facts_dir.glob("*/*.parquet")):
        return {}
    con = duckdb.connect()
    glob = str(facts_dir / "*" / "*.parquet").replace("'", "''")
    con.execute(
        'CREATE VIEW f AS SELECT cik, taxonomy, tag, "end", val, accn '
        f"FROM read_parquet('{glob}', hive_partitioning=true)"
    )
    con.execute("CREATE TABLE ps_tags(taxonomy VARCHAR, tag VARCHAR)")
    con.executemany("INSERT INTO ps_tags VALUES (?, ?)", per_share)
    covers: dict[str, dict[str, float]] = {}
    for cik, accn, val in con.execute(
        "SELECT cik, accn, max(val) FROM f WHERE taxonomy = 'dei'"
        " AND tag = 'EntityCommonStockSharesOutstanding' GROUP BY cik, accn"
    ).fetchall():
        covers.setdefault(cik, {})[accn] = float(val)
    last_ps: dict[str, date] = dict(
        con.execute(
            'SELECT f.cik, max(f."end") FROM f JOIN ps_tags p'
            " ON f.taxonomy = p.taxonomy AND f.tag = p.tag GROUP BY f.cik"
        ).fetchall()
    )
    return {
        cik: EquityEvidence(covers.get(cik, {}), last_ps.get(cik))
        for cik in covers.keys() | last_ps.keys()
    }


# Most-used taxonomy (ties → us-gaap), then its most-used ISO currency unit (ties → alphabetical).
_PROFILE_SQL = """
    WITH src AS (
        SELECT f.cik, f.taxonomy, f.unit FROM {source}
        WHERE f.taxonomy IN ('us-gaap', 'ifrs-full') AND regexp_matches(f.unit, '^[A-Z]{{3}}$')
    ),
    tax AS (
        SELECT cik, taxonomy,
               row_number() OVER (PARTITION BY cik
                   ORDER BY count(*) DESC, taxonomy = 'us-gaap' DESC) rk
        FROM src GROUP BY cik, taxonomy
    ),
    cur AS (
        SELECT src.cik, src.unit,
               row_number() OVER (PARTITION BY src.cik ORDER BY count(*) DESC, src.unit) rk
        FROM src JOIN tax ON src.cik = tax.cik AND src.taxonomy = tax.taxonomy AND tax.rk = 1
        GROUP BY src.cik, src.unit
    )
    SELECT tax.cik, tax.taxonomy, cur.unit
    FROM tax JOIN cur ON tax.cik = cur.cik AND cur.rk = 1
    WHERE tax.rk = 1
"""
_SOURCES: tuple[tuple[str, Basis], ...] = (
    ("f JOIN rev_tags r ON f.taxonomy = r.taxonomy AND f.tag = r.tag", "revenue"),
    ("f", "all facts"),
)


def facts_profiles(facts_dir: Path, tags: list[tuple[str, str]]) -> dict[str, FactsProfile]:
    if not any(facts_dir.glob("*/*.parquet")):
        return {}  # no company had kept facts: every CIK gets has_facts=false
    con = duckdb.connect()
    glob = str(facts_dir / "*" / "*.parquet").replace("'", "''")
    # Views can't take bound parameters; the path is ours (a local folder), quoted above.
    con.execute(
        "CREATE VIEW f AS SELECT cik, taxonomy, tag, unit "
        f"FROM read_parquet('{glob}', hive_partitioning=true)"
    )
    con.execute("CREATE TABLE rev_tags(taxonomy VARCHAR, tag VARCHAR)")
    con.executemany("INSERT INTO rev_tags VALUES (?, ?)", tags)
    has = con.execute(
        "SELECT DISTINCT cik FROM f WHERE taxonomy IN ('us-gaap', 'ifrs-full')"
    ).fetchall()
    out = {cik: FactsProfile(True, None, None) for (cik,) in has}
    for source, basis in _SOURCES:
        for cik, taxonomy, unit in con.execute(_PROFILE_SQL.format(source=source)).fetchall():
            if out[cik].taxonomy is None:
                out[cik] = FactsProfile(True, taxonomy, unit, basis)
    return out
