"""The Appendix D fixture build as a plain function, for the WT-11 spot-check sheet and its test.

Same steps as `tests/metrics/conftest.py::fixture_build` (WT-06's file, a pytest fixture, so not
callable from a script): the committed trimmed fixtures → facts_raw → companies → financials →
metrics. Prices are the committed Massive fixture bars, so price-tier values are not real; the
spot-checks use SEC-tier FY history points only.
"""

import zipfile
from pathlib import Path

import duckdb
import orjson
import polars as pl

from glint.contracts.metrics import load_registry
from glint.financials.build import build_financials
from glint.financials.concepts import load_concepts
from glint.fixtures.sec import FIXTURE_DIR, fixture_name
from glint.flags.engine import load_rules
from glint.ingest.prices.splits import adjust_for_splits
from glint.ingest.prices.stats import price_stats
from glint.ingest.sec.extract import extract_facts, load_whitelist
from glint.metrics.compute import SPLITS_SCHEMA
from glint.metrics.io import read_sql
from glint.metrics.params import load_params
from glint.metrics.share_classes import load_share_classes
from glint.metrics.stage import MetricsOutput, run_metrics
from glint.universe.build import build_companies
from glint.universe.predecessors import load_predecessors
from tests.metrics.conftest import AS_OF, AS_OF_PRICES, _bars  # pyright: ignore[reportPrivateUsage]


def build(folder: Path) -> tuple[MetricsOutput, pl.DataFrame]:
    """(metrics output, financials rows) for the fixture companies, built under `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    manifest = orjson.loads((FIXTURE_DIR / "manifest.json").read_bytes())
    ciks = {f["ticker"]: f["cik"] for f in manifest["fixtures"]}
    with (
        zipfile.ZipFile(folder / "submissions.zip", "w") as subs,
        zipfile.ZipFile(folder / "companyfacts.zip", "w") as facts,
    ):
        for t, cik in ciks.items():
            name = fixture_name(t)
            subs.writestr(f"CIK{cik}.json", (FIXTURE_DIR / f"{name}.submissions.json").read_bytes())
            facts.writestr(
                f"CIK{cik}.json", (FIXTURE_DIR / f"{name}.companyfacts.json").read_bytes()
            )
    (folder / "company_tickers_exchange.json").write_bytes(
        (FIXTURE_DIR / "company_tickers_exchange.json").read_bytes()
    )
    extract_facts(folder / "companyfacts.zip", folder / "facts_raw", source_sha256="fixture",
                  whitelist=load_whitelist())  # fmt: skip
    companies = build_companies(folder, AS_OF)
    concepts = load_concepts()
    with duckdb.connect(str(folder / "build.duckdb")) as con:
        build_financials(folder / "facts_raw", companies, load_predecessors(), concepts, con=con)
        fin = read_sql(con, "SELECT * FROM financials ORDER BY cik, line_item, basis, period_end")
    splits = pl.DataFrame(schema=SPLITS_SCHEMA)
    stats = price_stats(adjust_for_splits(_bars(), splits, AS_OF_PRICES), AS_OF_PRICES).stats
    out = run_metrics(
        companies, fin, stats, splits,
        as_of_fundamentals=AS_OF, as_of_prices=AS_OF_PRICES,
        share_classes=load_share_classes(), registry=load_registry(), params=load_params(),
        concepts=concepts, flag_cfg=load_rules(),
    )  # fmt: skip
    return out, fin
