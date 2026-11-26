"""Diluted-share comparisons across a split (`prices.split_adjusted`).

The earlier count is restated to the later count's basis by the splits between the two counts'
share-basis dates (`inputs.share_basis_date`: the first filing if the value is unchanged since,
else the latest filing), counting only splits the company's own filings confirm
(`prices.confirmed_splits`: a share count restated by about the split's ratio).

Synthetic cases. Latest quarter 2026-06-30 (filed 2026-08-05) vs 2025-06-30 (filed 2025-08-05):
  F  4-for-1 on 2026-01-15, confirmed:  100 → 412  = 412 / 400 − 1 = +3%   (raw +312%)
  R  1-for-20, confirmed:             2,000 → 104  = 104 / 100 − 1 = +4%   (raw −94.8%)
  D  1-for-10, confirmed, then issuance: 1,000 → 350 = 350 / 100 − 1 = +250% (raw −65%)
  A  4-for-1, year-ago count restated in the latest 10-Q (first filed 100, re-filed as 400; that
     restatement is also the evidence): 412 / 400 − 1, no second adjustment
  U  as A, but the comparative is re-filed *unchanged* (100), so it is still on the pre-split
     basis; another count confirms the split: 412 / 400 − 1
  W  4-for-1 on 2026-08-20, after both counts were first filed; both re-filed unchanged on
     2026-09-10: same basis, no adjustment: 105 / 100 − 1
  P  4-for-1 on 2025-07-20, after the year-ago period but before its filing (restated to 400)
  X  4-for-1 that no filing confirms (an ADR ratio change in the price table): unadjusted
  V  4-for-1, confirmed, but the year-ago count was re-filed changed ×0.4, which the split doesn't
     explain (ATVK: a correction across its 1-for-1,200), so its basis is unknown: unadjusted
  T  a 1.001 "split" with a count restated ×1.001: a correction, not evidence: unadjusted
  N  no split: 100 → 105

Real cases (financials rows from the 2026-10-30 SEC data, splits from the price store):
  NFLX  10-for-1 on 2025-11-17, confirmed by every comparative restated ×10
  ELVG  1-for-500 on 2026-03-17, confirmed by Q1 2025 restated ×0.002 in the Q1 2026 10-Q
  FUBO  1-for-12 on 2026-03-24, but no filing restates a count (post-split comparatives are the
        Hulu Live predecessor's), so it stays unadjusted; the year-ago count is legacy Fubo's,
        a different reporting entity, so no adjusted figure would be like-for-like anyway
  AZN   1-for-2 on 2026-02-02 in the price table: the ADS ratio change, not a share split
  AKTX  1-for-40 on 2026-03-31: an ADS ratio change; its only restatements (2024, ×0.002) are
        outside the window and at another ratio
  TTSH  3,000-for-1 on 2025-12-16: one leg of an odd-lot reverse/forward pair
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl
import pytest

from glint.metrics.defs.composites import piotroski_parts
from glint.metrics.history import build_history
from glint.metrics.params import Params
from glint.metrics.prices import confirmed_splits
from tests.metrics.frames import cell, run
from tests.metrics.helpers import companies, fin

D = date
NOW, AGO = D(2026, 6, 30), D(2025, 6, 30)
NOW_FILED, AGO_FILED = D(2026, 8, 5), D(2025, 8, 5)
SPLIT_DAY = D(2026, 1, 15)
FY0, FY1 = D(2025, 12, 31), D(2024, 12, 31)
FY0_FILED, FY1_FILED = D(2026, 2, 20), D(2025, 2, 20)
REFILED = D(2026, 9, 10)
TOL = Params().split_confirm_tolerance
Split = tuple[float, float, date]  # (split_from, split_to, execution_date)


@dataclass(frozen=True)
class Count:
    value: float
    filed: date  # latest filing
    first_value: float | None = None  # None: unchanged since the first filing
    first_filed: date | None = None  # None: first filed = filed


def c(value: float, filed: date, first_value: float | None = None,
      first_filed: date | None = None) -> Count:  # fmt: skip
    return Count(value, filed, first_value, first_filed)


def shares(
    cik: str, basis: str, end: date, n: Count | float, filed: date | None = None, *,
    item: str = "diluted_shares",
) -> tuple[object, ...]:  # fmt: skip
    n = n if isinstance(n, Count) else Count(n, filed or end)
    return (cik, item, basis, end, n.value, False, n.first_value, n.filed,
            n.first_filed or n.filed)  # fmt: skip


EVIDENCE_FIRST = D(2025, 11, 5)  # before SPLIT_DAY


def evidence(
    cik: str, factor: float, first: date = EVIDENCE_FIRST, last: date = NOW_FILED
) -> tuple[object, ...]:
    """A balance-sheet count first filed on `first`, re-filed on `last` restated × `factor`."""
    return shares(cik, "mrq", D(2025, 9, 30), c(1000 * factor, last, 1000, first),
                  item="shares_outstanding")  # fmt: skip


# cik → (year-ago count, latest count, split or None, evidence factor or None)
CASES: dict[str, tuple[Count, Count, Split | None, float | None]] = {
    "F": (c(100, AGO_FILED), c(412, NOW_FILED), (1, 4, SPLIT_DAY), 4),
    "R": (c(2000, AGO_FILED), c(104, NOW_FILED), (20, 1, SPLIT_DAY), 1 / 20),
    "D": (c(1000, AGO_FILED), c(350, NOW_FILED), (10, 1, SPLIT_DAY), 1 / 10),
    "A": (c(400, NOW_FILED, 100, AGO_FILED), c(412, NOW_FILED), (1, 4, SPLIT_DAY), None),
    "U": (c(100, NOW_FILED, None, AGO_FILED), c(412, NOW_FILED), (1, 4, SPLIT_DAY), 4),
    "W": (c(100, REFILED, None, AGO_FILED), c(105, REFILED, None, NOW_FILED),
          (1, 4, D(2026, 8, 20)), None),
    "P": (c(400, AGO_FILED), c(412, NOW_FILED), (1, 4, D(2025, 7, 20)), None),
    "X": (c(100, AGO_FILED), c(412, NOW_FILED), (1, 4, SPLIT_DAY), None),
    "V": (c(40, NOW_FILED, 100, AGO_FILED), c(412, NOW_FILED), (1, 4, SPLIT_DAY), 4),
    "T": (c(100, AGO_FILED), c(105.1, NOW_FILED), (1000, 1001, SPLIT_DAY), 1.001),
    "N": (c(100, AGO_FILED), c(105, NOW_FILED), None, None),
}  # fmt: skip


def split_table(rows: list[tuple[str, Split]]) -> pl.DataFrame:
    return pl.DataFrame(
        [(t, s[2], float(s[0]), float(s[1])) for t, s in rows],
        schema={"ticker": pl.String, "execution_date": pl.Date, "split_from": pl.Float64,
                "split_to": pl.Float64}, orient="row",
    )  # fmt: skip


def _splits() -> pl.DataFrame:
    return split_table([(cik, s) for cik, (_, _, s, _) in CASES.items() if s])


def _rows() -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for cik, (ago, now, _, factor) in CASES.items():
        rows += [shares(cik, "q", AGO, ago), shares(cik, "q", NOW, now)]
        if factor is not None:
            rows.append(evidence(cik, factor))
    # W's split (2026-08-20) is confirmed by a count first filed before it and restated after
    rows.append(evidence("W", 4, NOW_FILED, REFILED))
    # F: TTM net income for eps_growth_yoy (EPS 824/412 = 2.0 vs 200/(100 × 4) = 0.5)
    rows += [("F", "net_income", "ttm", NOW, 824), ("F", "net_income", "ttm", AGO, 200)]
    # Piotroski "no new shares" on FY counts: F 4-for-1 (100 → 400, none new), D 1-for-10 then
    # issuance (1,000 → 300, i.e. 100 → 300 on the new basis), X unconfirmed (100 → 400)
    rows += [shares("F", "fy", FY1, 100, FY1_FILED), shares("F", "fy", FY0, 400, FY0_FILED)]
    rows += [shares("D", "fy", FY1, 1000, FY1_FILED), shares("D", "fy", FY0, 300, FY0_FILED)]
    rows += [shares("X", "fy", FY1, 100, FY1_FILED), shares("X", "fy", FY0, 400, FY0_FILED)]
    return rows


def _companies(ciks: object = CASES) -> list[dict[str, object]]:
    return [{"cik": c, "tickers": [c], "primary_ticker": c} for c in ciks]  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def out() -> pl.DataFrame:
    return run(_rows(), _companies(), splits=_splits())


@pytest.mark.parametrize(
    ("cik", "value", "code"),
    [
        ("F", 0.03, "DERIVED_INPUT"),  # forward split
        ("R", 0.04, "DERIVED_INPUT"),  # reverse split
        ("D", 2.5, "DERIVED_INPUT"),  # reverse split, then heavy issuance: still dilution
        ("A", 0.03, None),  # comparative already restated: no second adjustment
        ("U", 0.03, "DERIVED_INPUT"),  # comparative re-filed unchanged: still pre-split
        ("W", 0.05, None),  # split after both first filings; re-filed unchanged: same basis
        ("P", 0.03, None),  # split before the year-ago filing: already in that count
        ("X", 3.12, None),  # no filing confirms the split: unadjusted
        ("V", 9.3, None),  # year-ago count re-filed ×0.4 across a ×4 split: basis unknown
        ("T", 0.051, None),  # a ×1.001 restatement is a correction, not evidence
        ("N", 0.05, None),
    ],
)
def test_share_count_change(out: pl.DataFrame, cik: str, value: float, code: str | None) -> None:
    v, c, _ = cell(out, cik, "share_count_change_yoy")
    assert v == pytest.approx(value, abs=1e-9)
    assert c == code


def test_note_states_the_adjustment(out: pl.DataFrame) -> None:
    _, _, msg = cell(out, "R", "share_count_change_yoy")
    assert msg == (
        "diluted_shares_q_1y × 0.05 for a split between the filing its count is from "
        "(2025-08-05) and diluted_shares_q's (2026-08-05)"
    )


def test_reverse_split_then_issuance_is_flagged(out: pl.DataFrame) -> None:
    """Dilution watch reads share_count_change_yoy ≥ 0.10: D must pass, F and R must not
    (X and V pass too: their splits are unadjusted, so the raw change stands)."""
    hits = {c for c in CASES if (cell(out, c, "share_count_change_yoy")[0] or 0) >= 0.10}
    assert hits == {"D", "X", "V"}


def test_eps_growth_split_adjusted(out: pl.DataFrame) -> None:
    v, c, _ = cell(out, "F", "eps_growth_yoy")
    assert v == pytest.approx(3.0)  # 2.0 / 0.5 − 1 (unadjusted: 2.0 / 2.0 − 1 = 0)
    assert c == "DERIVED_INPUT"


def test_piotroski_no_new_shares(out: pl.DataFrame) -> None:
    parts = out.select("cik", no_new=piotroski_parts(Params())["no_new_shares"])
    got = dict(parts.filter(pl.col("cik").is_in(["F", "D", "X"])).iter_rows())
    # F 400 ≤ 100 × 4 ✓, D 300 ≤ 1,000 / 10 ✗; X unconfirmed: 400 ≤ 100 ✗
    assert got == {"F": 1.0, "D": 0.0, "X": 0.0}


def test_history_points() -> None:
    """The drawer series uses the same rule (TTM points read the Q counts)."""
    some = ("F", "D", "A", "U", "W", "X")
    rows = [r for r in _rows() if r[0] in some]
    for cik in some:  # history points need a flow at the period end
        rows += [(cik, "revenue", "ttm", NOW, 10), (cik, "revenue", "ttm", AGO, 10)]
    h = build_history(
        companies(_companies(some)), fin(rows), Params(), window=45, splits=_splits()
    ).filter((pl.col("metric_id") == "share_count_change_yoy") & (pl.col("period_end") == NOW))
    got = dict(h.select("cik", "value").iter_rows())
    want = {"F": 0.03, "D": 2.5, "A": 0.03, "U": 0.03, "W": 0.05, "X": 3.12}
    assert got == pytest.approx(want)


# --- real cases -----------------------------------------------------------------------------

REAL_SPLITS = split_table([
    ("NFLX", (1, 10, D(2025, 11, 17))),
    ("ELVG", (500, 1, D(2026, 3, 17))),
    ("FUBO", (12, 1, D(2026, 3, 24))),
    ("AZN", (2, 1, D(2026, 2, 2))),
    ("AKTX", (40, 1, D(2026, 3, 31))),
    ("TTSH", (1, 3000, D(2025, 12, 16))),
])  # fmt: skip


def q(cik: str, end: date, *count: Any, basis: str = "q") -> tuple[object, ...]:
    """A diluted count row; `count` is `c()`'s (value, filed[, first_value[, first_filed]])."""
    return shares(cik, basis, end, c(*count))


REAL_ROWS: list[tuple[object, ...]] = [
    # NFLX: latest quarter vs its restated comparative (no adjustment), and the 2025-03-31 TTM
    # point vs 2024-03-31, first filed before the split and never restated (adjusted)
    q("NFLX", D(2024, 3, 31), 441_654_000, D(2025, 4, 18), None, D(2024, 4, 22)),
    q("NFLX", D(2025, 3, 31), 4_369_623_000, D(2026, 4, 17), 436_962_000, D(2025, 4, 18)),
    q("NFLX", D(2025, 9, 30), 4_340_392_000, D(2026, 10, 21), 434_039_000, D(2025, 10, 22)),
    q("NFLX", D(2026, 9, 30), 4_195_127_000, D(2026, 10, 21)),
    ("NFLX", "revenue", "ttm", D(2025, 3, 31), 1), ("NFLX", "revenue", "ttm", D(2024, 3, 31), 1),
    # ELVG: the year-ago count re-filed unchanged (pre-split); Q1 2025 restated ×0.002
    q("ELVG", D(2025, 3, 31), 828_914, D(2026, 5, 20), 414_448_757, D(2025, 5, 15)),
    q("ELVG", D(2025, 6, 30), 414_448_757, D(2026, 8, 14), None, D(2025, 8, 8)),
    q("ELVG", D(2026, 6, 30), 834_042, D(2026, 8, 14)),
    # FUBO: legacy Fubo year-ago count, post-split combined-company count; nothing restated
    q("FUBO", D(2025, 6, 30), 341_683_408, D(2025, 8, 11)),
    q("FUBO", D(2026, 6, 30), 32_758_090, D(2026, 8, 5)),
    # AZN: FY counts in ordinary shares, FY2024 re-filed unchanged after the ADS ratio change
    q("AZN", D(2024, 12, 31), 1_563_000_000, D(2026, 2, 24), None, D(2025, 2, 18), basis="fy"),
    q("AZN", D(2025, 12, 31), 1_562_000_000, D(2026, 2, 24), basis="fy"),
    ("AZN", "net_income", "ttm", D(2025, 12, 31), 10_225_000_000),
    ("AZN", "net_income", "ttm", D(2024, 12, 31), 7_035_000_000),
    # AKTX: ordinary-share counts; the 2024 restatement (×0.002) predates the 2026 ratio change
    q("AKTX", D(2023, 6, 30), 20_254_118, D(2024, 9, 6), 10_115_005_727, D(2024, 8, 19)),
    q("AKTX", D(2025, 6, 30), 62_943_895_665, D(2026, 8, 13), None, D(2025, 8, 13)),
    q("AKTX", D(2026, 6, 30), 143_317_469_445, D(2026, 8, 13)),
    # TTSH: FY counts unchanged across the odd-lot pair
    q("TTSH", D(2024, 12, 31), 43_851_653, D(2026, 2, 26), None, D(2025, 2, 27), basis="fy"),
    q("TTSH", D(2025, 12, 31), 43_697_270, D(2026, 2, 26), basis="fy"),
    ("TTSH", "net_income", "ttm", D(2025, 12, 31), -4_494_000),
    ("TTSH", "net_income", "ttm", D(2024, 12, 31), 2_321_000),
]  # fmt: skip
REAL = ("NFLX", "ELVG", "FUBO", "AZN", "AKTX", "TTSH")


@pytest.fixture(scope="module")
def real() -> pl.DataFrame:
    return run(REAL_ROWS, _companies(REAL), splits=REAL_SPLITS)


def test_real_confirmed_splits() -> None:
    tickers = pl.DataFrame({"cik": list(REAL), "primary_ticker": list(REAL)})
    got = confirmed_splits(REAL_SPLITS, fin(REAL_ROWS), tickers, TOL)
    assert sorted(got["ticker"]) == ["ELVG", "NFLX"]


@pytest.mark.parametrize(
    ("cik", "metric_id", "value", "code"),
    [
        # 834,042 / (414,448,757 / 500) − 1 (unadjusted −99.8%)
        ("ELVG", "share_count_change_yoy", 0.0062064, "DERIVED_INPUT"),
        ("NFLX", "share_count_change_yoy", -0.0334682, None),  # comparative restated ×10
        ("FUBO", "share_count_change_yoy", -0.9041274, None),  # unconfirmed: stays unadjusted
        ("AKTX", "share_count_change_yoy", 1.2769082, None),  # 143.3B / 62.9B − 1
        # (10,225 / 1,562) / (7,035 / 1,563) − 1, not halved by the ADS ratio change
        ("AZN", "eps_growth_yoy", 0.4543776, None),
        # (−4.494M / 43.70M) / (2.321M / 43.85M) − 1, not ×3,000 by the odd-lot leg
        ("TTSH", "eps_growth_yoy", -2.9430751, None),
    ],
)
def test_real_cases(
    real: pl.DataFrame, cik: str, metric_id: str, value: float, code: str | None
) -> None:
    v, c, _ = cell(real, cik, metric_id)
    assert v == pytest.approx(value, abs=1e-6)
    assert c == code


def test_real_nflx_history_point_adjusted() -> None:
    """NFLX TTM 2025-03-31 vs 2024-03-31: 4,369.6M / (441.654M × 10) − 1 (raw +889%)."""
    h = build_history(
        companies(_companies(["NFLX"])), fin([r for r in REAL_ROWS if r[0] == "NFLX"]),
        Params(), window=45, splits=REAL_SPLITS,
    ).filter((pl.col("metric_id") == "share_count_change_yoy")
             & (pl.col("period_end") == D(2025, 3, 31)))  # fmt: skip
    assert h["value"].to_list() == pytest.approx([4_369_623_000 / 4_416_540_000 - 1])
