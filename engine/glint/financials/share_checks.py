"""Share-count plausibility (§4.3 rule 11, fix-shares). Pure.

Two checks, both against the filer's own numbers:

1. **Diluted scale.** For a period with net income and diluted EPS, NI ÷ EPS is the diluted count
   the income statement implies. A filed `diluted_shares` whose ratio to it lands within
   `scale_band` of a power of 1,000 (10³, 10⁶, 10⁻³, 10⁻⁶) was tagged in the wrong scale (WAT
   2026 10-Qs: 98,204,000,000 for 98.2M; HUBG: 60,333 for 60.3M). It is kept as the *filed value*
   ÷ that power, flagged derived, with the filed value and the check in `inputs`.
   - A ratio beyond `scale_reject_ratio` either way that isn't in a band is rejected (null),
     never rescaled.
   - **Corroboration.** EPS can be mis-scaled too (Taboola's 2026 10-Q: 6M diluted EPS −40 for
     −$0.04, shares ×1,000), which fools NI ÷ EPS. So a rescaled value must also be within
     `same_filing_max_ratio` of the nearest diluted count from a filing that needed no
     correction, when one is within `stale_days`. If it isn't, the filed value is kept when *it*
     agrees with that neighbour, and otherwise the period is rejected.
   - **Same filing.** A scale error belongs to a filing. A period without a check (EPS under a
     cent threshold) takes the correction, or the rejection, of its filing's checked periods when
     they all agree and it is within `same_filing_max_ratio` of one of them. A year-ago
     comparative is checked on its own, so year-on-year changes don't mix scales.
   - Diluted counts below `min_count` are dropped (pre-IPO quarters with 1 share).
2. **Placeholder counts.** A cover-page or balance-sheet count below `min_count` (pre-IPO or
   subsidiary filings: 1, 100, 1,000 shares) or below `placeholder_ratio` × a checked diluted
   count of the same or a later period (AVEX: 1,000 vs 52.8M) isn't the listed company's count.
   Such counts are dropped from the latest end backwards, so the next count, or the diluted
   fallback, is used.
3. **One class, not the company.** A count below `class_ratio` × the diluted count that the
   *same filing* reports for a period ending the same day is one class or instrument tagged
   without its class dimension (IHRT's Q3 2025 10-Q: its 5,039,323 special warrants as the
   undimensioned `CommonStockSharesOutstanding`, against 155,187,000 diluted for the quarter).
   Within one filing both counts are on the same split basis, so a reverse split between filings
   can't trip it; the filing's diluted count must also agree (within `same_filing_max_ratio`)
   with a checked diluted count for that period, so a mis-scaled one (WAT) can't either. Such
   counts are dropped at any date. When the latest one is dropped, older counts aren't used as
   the current count (they may predate a split the filing has restated): the diluted fallback
   of that date or later is, or nothing (normalize._set_share_count).
"""

import dataclasses
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from glint.financials.concepts import ShareCheckParams
from glint.financials.facts import Fact
from glint.financials.periods import Period
from glint.financials.select import Value

REJECT = "reject"


@dataclass
class ScaleResult:
    values: dict[Period, Value]
    checked: set[Period] = field(default_factory=set[Period])  # NI/EPS-consistent (after rescale)
    rescaled: dict[Period, int] = field(default_factory=dict[Period, int])  # → power of 1,000
    rejected: set[Period] = field(default_factory=set[Period])
    warnings: list[str] = field(default_factory=list[str])


def scale_power(ratio: float, band: float) -> int | None:
    """k when `ratio` is within ±`band` of 1000**k (k ≠ 0 means a scale error), else None."""
    if ratio <= 0:
        return None
    k = round(math.log10(ratio) / 3)
    return k if abs(ratio / 1000.0**k - 1) <= band else None


def _implied(
    period: Period,
    net_income: Mapping[Period, Value],
    eps: Mapping[Period, Value],
    p: ShareCheckParams,
) -> float | None:
    ni, e = net_income.get(period), eps.get(period)
    if ni is None or e is None:
        return None
    if abs(e.value) < p.check_min_eps or abs(ni.value) < p.check_min_net_income:
        return None
    return ni.value / e.value


def _op(k: int) -> str:
    return f"{'÷' if k > 0 else '×'} {1000 ** abs(k):,}"


def _within(a: float, b: float, max_ratio: float) -> bool:
    return b > 0 and 1 / max_ratio <= a / b <= max_ratio


def _rescaled(v: Value, k: int, first_k: int | None, why: str) -> Value:
    first = v.first_filed_value
    return dataclasses.replace(
        v,
        value=v.value / 1000.0**k,
        source_tag=None,
        derived=True,
        first_filed_value=first / 1000.0**first_k
        if first is not None and first_k is not None
        else first,
        inputs=(f"filed {v.source_tag} {v.value:,.0f} (accn {v.source_accn}) {_op(k)}: {why}",),
        lineage=v.tag_key,
    )


@dataclass
class _Check:
    """Pass-1 outcome for one period: k (0 = consistent), REJECT, or None (no check)."""

    verdict: int | str | None
    why: str = ""
    implied: float | None = None


def _check_all(
    diluted: Mapping[Period, Value],
    net_income: Mapping[Period, Value],
    eps: Mapping[Period, Value],
    p: ShareCheckParams,
) -> dict[Period, _Check]:
    out: dict[Period, _Check] = {}
    for period, v in diluted.items():
        implied = _implied(period, net_income, eps, p)
        if implied is None or v.derived:
            out[period] = _Check(None)
            continue
        ratio = v.value / implied
        if ratio <= 0:
            # NI and EPS of opposite sign (NI includes noncontrolling interests or preferred
            # dividends; EPS is to common): the check doesn't apply.
            out[period] = _Check(None)
            continue
        why = (
            f"net_income {net_income[period].value:,.0f} / eps_diluted {eps[period].value:g} "
            f"= {implied:,.0f}"
        )
        k = scale_power(ratio, p.scale_band)
        if k is not None:
            out[period] = _Check(k, why, implied)
        elif ratio >= p.scale_reject_ratio or ratio <= 1 / p.scale_reject_ratio:
            out[period] = _Check(REJECT, f"{why} (ratio {ratio:.3g}, not a power of 1,000)")
        else:
            out[period] = _Check(None)  # moderate gaps: NI to common vs NI, two-class EPS
    return out


def _corroborate(
    diluted: Mapping[Period, Value],
    checks: dict[Period, _Check],
    p: ShareCheckParams,
    stale_days: int,
) -> None:
    """Rescales that disagree with a diluted count from a clean filing are undone or rejected."""
    dirty = {diluted[q].source_accn for q, c in checks.items() if c.verdict not in (None, 0)}
    clean = [q for q in diluted if diluted[q].source_accn not in dirty]
    for period, c in checks.items():
        if not isinstance(c.verdict, int) or c.verdict == 0:
            continue
        near = [q for q in clean if abs((q.end - period.end).days) <= stale_days]
        if not near:
            continue  # every filing in reach is off the same way (HUBG): nothing to compare
        ref = diluted[min(near, key=lambda q: (abs((q.end - period.end).days), q.end))]
        v = diluted[period]
        if _within(v.value / 1000.0**c.verdict, ref.value, p.same_filing_max_ratio):
            continue
        against = f"{ref.period.label()} {ref.value:,.0f} (accn {ref.source_accn})"
        if _within(v.value, ref.value, p.same_filing_max_ratio):
            checks[period] = _Check(0, f"{c.why} disagrees, but the filed value agrees with "
                                       f"{against}; kept as filed")  # fmt: skip
        else:
            checks[period] = _Check(REJECT, f"{c.why}, but {_op(c.verdict)} disagrees with "
                                            f"{against}; the check itself is off")  # fmt: skip


def _same_filing(diluted: Mapping[Period, Value], checks: dict[Period, _Check],
                 p: ShareCheckParams) -> None:  # fmt: skip
    """Unchecked periods take their filing's verdict when all its checked periods agree."""
    by_filing: dict[str, dict[int | str, list[Period]]] = {}
    for q, c in checks.items():
        if c.verdict is not None:
            accn = diluted[q].source_accn or ""
            by_filing.setdefault(accn, {}).setdefault(c.verdict, []).append(q)
    for period, c in list(checks.items()):
        v = diluted[period]
        verdicts = by_filing.get(v.source_accn or "", {})
        if c.verdict is not None or v.derived or len(verdicts) != 1:
            continue
        ((verdict, peers),) = verdicts.items()
        near = [q for q in peers if _within(v.value, diluted[q].value, p.same_filing_max_ratio)]
        if verdict == 0 or not near:
            continue
        peer = diluted[near[0]]
        checks[period] = _Check(
            verdict,
            f"same filing as {peer.period.label()} ({peer.value:,.0f} filed): "
            + checks[near[0]].why,
        )


def check_diluted_scale(
    diluted: Mapping[Period, Value],
    net_income: Mapping[Period, Value],
    eps: Mapping[Period, Value],
    p: ShareCheckParams,
    stale_days: int,
) -> ScaleResult:
    checks = _check_all(diluted, net_income, eps, p)
    _corroborate(diluted, checks, p, stale_days)
    _same_filing(diluted, checks, p)
    out = ScaleResult(values={})
    for period, filed in sorted(diluted.items()):
        c, v = checks[period], filed
        if c.verdict == REJECT:
            out.rejected.add(period)
            out.warnings.append(
                f"diluted_shares {period.label()}: filed {v.value:,.0f} disagrees with "
                f"{c.why}; dropped"
            )
            continue
        if isinstance(c.verdict, int) and c.verdict != 0:
            k = c.verdict
            first = v.first_filed_value
            first_k = (
                scale_power(first / c.implied, p.scale_band)
                if first is not None and c.implied
                else (k if first == v.value else None)
            )
            v = _rescaled(v, k, first_k, c.why)
            out.rescaled[period] = k
            out.warnings.append(
                f"diluted_shares {period.label()}: filed {filed.value:,.0f} "
                f"{_op(k)} ({c.why}); rescaled"
            )
        if c.implied is not None and c.verdict != REJECT:
            out.checked.add(period)
        elif c.verdict == 0 and c.why:
            out.warnings.append(f"diluted_shares {period.label()}: {c.why}")
        if v.value < p.min_count:
            out.rejected.add(period)
            out.checked.discard(period)
            out.warnings.append(
                f"diluted_shares {period.label()}: {v.value:,.0f} is below "
                f"{p.min_count:,.0f} shares, not a listed company's count; dropped"
            )
            continue
        out.values[period] = v
    return out


def _checked_diluted_at_or_after(
    end: date, diluted: Mapping[Period, Value], checked: set[Period]
) -> Value | None:
    hits = [p for p in checked if p in diluted and p.end >= end]
    return diluted[min(hits, key=lambda p: (p.end, p.start or p.end))] if hits else None


def same_filing_diluted(facts: Iterable[Fact]) -> dict[tuple[str, date], tuple[Period, float]]:
    """(accn, end) → the diluted count that filing reports for its shortest period ending that
    day (the quarter's, when filed)."""
    out: dict[tuple[str, date], tuple[Period, float]] = {}
    for f in facts:
        if f.start is None:
            continue
        key, period = (f.accn, f.end), Period(end=f.end, start=f.start)
        if key not in out or period.days < out[key][0].days:
            out[key] = (period, f.val)
    return out


def class_only_reason(
    v: Value,
    filed: Mapping[tuple[str, date], tuple[Period, float]],
    diluted: Mapping[Period, Value],
    checked: set[Period],
    p: ShareCheckParams,
) -> str | None:
    """Why `v` is one class's count, not the company's (rule 3), or None."""
    hit = filed.get((v.source_accn or "", v.period.end))
    if hit is None:
        return None
    period, same = hit
    if v.value >= p.class_ratio * same:
        return None
    agrees = [
        q
        for q in checked
        if q in diluted
        and q.end == v.period.end
        and _within(same, diluted[q].value, p.same_filing_max_ratio)
    ]
    if not agrees:
        return None
    return (
        f"is below {p.class_ratio:g} × the {same:,.0f} diluted_shares the same filing reports for "
        f"{period.label()}: one class or instrument, not the company's count"
    )


def drop_placeholder_counts(
    shares: Mapping[date, Value],
    diluted: Mapping[Period, Value],
    checked: set[Period],
    p: ShareCheckParams,
    filed_diluted: Mapping[tuple[str, date], tuple[Period, float]] | None = None,
) -> tuple[dict[date, Value], list[str]]:
    """Counts with implausible ones removed: any below `min_count` or below `class_ratio` × the
    diluted count of the same filing and day (`filed_diluted`, from `same_filing_diluted`); then,
    from the latest end backwards, counts below `placeholder_ratio` × a checked diluted count
    dated at or after."""
    kept: dict[date, Value] = {}
    warnings: list[str] = []
    for end, v in sorted(shares.items()):
        class_only = class_only_reason(v, filed_diluted or {}, diluted, checked, p)
        if v.value < p.min_count:
            warnings.append(
                f"shares_outstanding {end}: {v.source_tag} {v.value:,.0f} is below "
                f"{p.min_count:,.0f} shares, not a listed company's count; dropped"
            )
        elif class_only is not None:
            warnings.append(
                f"shares_outstanding {end}: {v.source_tag} {v.value:,.0f} (accn {v.source_accn}) "
                f"{class_only}; dropped"
            )
        else:
            kept[end] = v
    while kept:
        end = max(kept)
        v = kept[end]
        dil = _checked_diluted_at_or_after(end, diluted, checked)
        if dil is None or v.value >= p.placeholder_ratio * dil.value:
            break
        warnings.append(
            f"shares_outstanding {end}: {v.source_tag} {v.value:,.0f} is below "
            f"{p.placeholder_ratio:g} × diluted_shares {dil.value:,.0f} ({dil.period.label()}); "
            "dropped"
        )
        del kept[end]
    return kept, warnings
