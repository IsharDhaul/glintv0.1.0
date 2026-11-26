"""Building blocks for metric functions: inputs with null reasons, guarded results, the registry.

A metric function takes the inputs frame and returns a `MetricResult`: one value per company and,
per company, at most one note (`metric_notes` is keyed by cik + metric id). Null precedence:

1. a missing input, with that input's own reason. When several inputs are missing, the reason that
   would still hold once the others were filled wins (`INPUT_PRECEDENCE`): INSUFFICIENT_HISTORY
   first (only time fills it), then not meaningful (n/m), then STALE_DATA, then MISSING_INPUT and
   anything else. Within a tier, the first input in the order the function lists them. An input
   is n/m only on positive evidence (a tagged value or the company's classification), never
   because a tag is absent; that is MISSING_INPUT;
2. the metric's guards (e.g. `NEGATIVE_DENOMINATOR`), in order;
3. otherwise a value; it carries `ASSUMED_TAX_RATE` or `DERIVED_INPUT` if one applies.

Applicability (§4.5) is applied afterwards by `glint.metrics.applicability` and overrides all of it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache

import polars as pl

from glint.contracts.enums import NOTE_DISPLAY, LineItem, NoteCode, NoteDisplay
from glint.financials.concepts import ConceptMap, load_concepts
from glint.metrics.inputs import MRQ, MRQ_1Y, MRQ_2Y, TTM, TTM_1Y, Slot, col_name
from glint.metrics.params import Params

C = NoteCode


@cache
def _concepts() -> ConceptMap:
    return load_concepts()


@dataclass(frozen=True)
class In:
    """A value a metric reads, with its null reason and whether it is a derived input."""

    label: str
    value: pl.Expr
    code: pl.Expr
    message: pl.Expr
    derived: pl.Expr
    note: pl.Expr | None = None  # how the ⓘ note names this input, when not just `label`
    item: LineItem | None = None  # provenance, for `glint metrics --explain`
    slot: Slot | None = None
    metric_id: str | None = None

    def __neg__(self) -> pl.Expr:
        return -self.value


def _s(e: pl.Expr) -> pl.Expr:
    return e.cast(pl.String)


def _end_missing_message(slot: Slot) -> str:
    return {
        "ttm": "no TTM period yet",
        "ttm_1y": "no TTM period about a year before the latest",
        "mrq": "no balance sheet yet",
        "mrq_1y": "no balance sheet about a year before the latest",
        "q": "no quarterly diluted share count yet",
        "q_1y": "no quarter about a year before the latest",
    }.get(slot.name, f"no fiscal year {slot.name.removeprefix('fy')} years before the latest")


def item(i: LineItem, slot: Slot, label: str | None = None) -> In:
    """Line item `i` at `slot`, with the reason when it's null (mirrors WT-03's coverage gaps)."""
    name = col_name(i, slot)
    label = label or f"{i.value}_{slot.name}"
    end = pl.col(slot.end_col)
    na = sorted(s.value for s in _concepts()[i].not_applicable)
    last = pl.col(f"{i.value}__last")
    note = _concepts()[i].note
    tail = f". {note}" if note else ""
    code = (
        pl.when(pl.col(name).is_not_null())
        .then(pl.lit(None, pl.String))
        .when(pl.col("sector").is_in(na))
        .then(pl.lit(C.NOT_APPLICABLE_SECTOR.value))
        .when(end.is_null())
        .then(pl.lit(C.INSUFFICIENT_HISTORY.value))
    )
    message = (
        pl.when(pl.col(name).is_not_null())
        .then(pl.lit(None, pl.String))
        .when(pl.col("sector").is_in(na))
        .then(pl.format(f"{i.value} is n/a for {{}}", "sector"))
        .when(end.is_null())
        .then(pl.lit(f"{label}: {_end_missing_message(slot)}"))
    )
    if slot in (TTM, TTM_1Y):
        recent = pl.col(f"{i.value}__lastfyq") > end.dt.offset_by("-1y")
        code = code.when(recent).then(pl.lit(C.INSUFFICIENT_HISTORY.value))
        message = message.when(recent).then(
            pl.format(f"{label}: no 4 contiguous quarters (or FY + YTD bridge) to {{}}", _s(end))
        )
    code = code.otherwise(pl.lit(C.MISSING_INPUT.value))
    message = message.otherwise(
        pl.when(last.is_null())
        .then(pl.lit(f"{label}: {i.value} is not reported{tail}"))
        .otherwise(
            pl.format(f"{label}: nothing for {{}} (latest value {{}}){tail}", _s(end), _s(last))
        )
    )
    derived = pl.col(name + "__d").fill_null(False)
    return In(label, pl.col(name), code, message, derived, item=i, slot=slot)


PRIOR_SLOT = {MRQ: MRQ_1Y, MRQ_1Y: MRQ_2Y}
NONE_EVEN_IF_TAGGED_BEFORE = frozenset(
    {LineItem.DEBT_CURRENT}
)  # user decision 2026-10-30  # the balance sheet about a year before each slot


def optional(i: LineItem, slot: Slot) -> In:
    """A balance-sheet part that counts as none when not tagged at the slot's date (user decision
    2026-10-30: preferred, minority_interest, st_investments; debt_current per WT-03). It is
    MISSING_INPUT instead when the part was tagged on the balance sheet about a year earlier
    (user decision after the NVDA hand-check), except current debt, which still counts as none
    and whose note gives last year's value (nothing due within a year is common). Null when
    there is no balance sheet at that slot. The ⓘ note names it."""
    base = item(i, slot)
    name = col_name(i, slot)
    prior = PRIOR_SLOT[slot]
    prior_value = pl.col(col_name(i, prior))
    keep_none = i in NONE_EVEN_IF_TAGGED_BEFORE
    gone = pl.lit(False) if keep_none else pl.col(name).is_null() & prior_value.is_not_null()
    absent = pl.col(name).is_null() & pl.col(slot.end_col).is_not_null() & ~gone
    note = pl.lit(f"{base.label} (not tagged, counted as none)")
    if keep_none:
        note = pl.when(prior_value.is_not_null()).then(
            pl.format(f"{base.label} (not tagged, counted as none; {{}} a year earlier)",
                      prior_value.cast(pl.Int64))
        ).otherwise(note)  # fmt: skip
    return In(
        base.label,
        pl.when(absent).then(0.0).otherwise(pl.col(name)),
        pl.when(gone).then(pl.lit(C.MISSING_INPUT.value)).otherwise(base.code),
        pl.when(gone)
        .then(
            pl.format(
                f"{base.label}: tagged at {{}} but not at {{}}",
                _s(pl.col(prior.end_col)),
                _s(pl.col(slot.end_col)),
            )
        )
        .otherwise(base.message),
        base.derived | absent,
        pl.when(absent).then(note),
        item=i,
        slot=slot,
    )


def shareholder_flow(i: LineItem, slot: Slot) -> In:
    """Dividends paid, buybacks or stock issued: untagged counts as none (0, noted) when the
    period's cash-flow statement is tagged (CFO present at the slot), else the usual reason
    (user decision 2026-10-30: a non-payer files no dividend line)."""
    base = item(i, slot)
    name = col_name(i, slot)
    absent = pl.col(name).is_null() & pl.col(col_name(LineItem.CFO, slot)).is_not_null()
    note = f"{base.label} (not tagged; cash-flow statement filed, counted as none)"
    return In(
        base.label,
        pl.when(absent).then(0.0).otherwise(pl.col(name)),
        base.code,
        base.message,
        base.derived | absent,
        pl.when(absent).then(pl.lit(note)),
        item=i,
        slot=slot,
    )


def average(i: LineItem) -> In:
    """(MRQ + the balance sheet about a year earlier) / 2 (§2.4 basis)."""
    now, ago = item(i, MRQ), item(i, MRQ_1Y)
    first = now.value.is_null()
    return In(
        f"average {i.value}",
        (now.value + ago.value) / 2,
        pl.when(first).then(now.code).otherwise(ago.code),
        pl.when(first).then(now.message).otherwise(ago.message),
        now.derived | ago.derived,
        item=i,  # slot None: both MRQ and MRQ_1Y (see `glint.metrics.explain`)
    )


def metric_in(metric_id: str) -> In:
    """An earlier metric's result, used as an input (e.g. market_cap inside pe_ttm)."""
    code = pl.col(f"{metric_id}__code")
    return In(
        metric_id,
        pl.col(metric_id),
        code,
        pl.col(f"{metric_id}__msg"),
        code == C.DERIVED_INPUT.value,
        metric_id=metric_id,
    )


def column_in(column: str, code: NoteCode, message: str | pl.Expr, label: str | None = None) -> In:
    """A plain column (price stats, share count) with a fixed reason when it's null."""
    msg = pl.lit(message) if isinstance(message, str) else message
    return In(label or column, pl.col(column), pl.lit(code.value), msg, pl.lit(False))


INPUT_PRECEDENCE: tuple[frozenset[NoteCode], ...] = (
    frozenset({C.INSUFFICIENT_HISTORY}),
    frozenset(c for c, d in NOTE_DISPLAY.items() if d is NoteDisplay.NOT_MEANINGFUL),
    frozenset({C.STALE_DATA}),
)  # then every other code (MISSING_INPUT, ...) in input order; see the module docstring


@dataclass(frozen=True)
class Guard:
    """Null the value with `code` when `when` is true (checked after inputs are present)."""

    when: pl.Expr
    code: NoteCode
    message: str | pl.Expr


def den_le_zero(den: In, what: str | None = None) -> Guard:
    return Guard(den.value <= 0, C.NEGATIVE_DENOMINATOR, f"{what or den.label} ≤ 0")


@dataclass(frozen=True)
class Info:
    """A note on a present value (ASSUMED_TAX_RATE); beats DERIVED_INPUT."""

    when: pl.Expr
    code: NoteCode
    message: str | pl.Expr


@dataclass(frozen=True)
class MetricExprs:
    value: pl.Expr
    code: pl.Expr
    message: pl.Expr
    inputs: tuple[In, ...] = ()


def _lit(m: str | pl.Expr) -> pl.Expr:
    return pl.lit(m) if isinstance(m, str) else m


def first(cases: Sequence[tuple[pl.Expr, pl.Expr]], default: pl.Expr) -> pl.Expr:
    """The value of the first case whose condition is true, else `default` (a when/then chain)."""
    out = default
    for cond, value in reversed(cases):
        out = pl.when(cond).then(value).otherwise(out)
    return out


def lease_not_counted() -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """INPUT_EXCLUDES on a value built from MRQ total_debt when the company tags a finance lease
    but no filing says which balance-sheet line holds it, so total_debt leaves it out (WT-03's
    rule; `companies.finance_lease_status`, user decision 2026-11-22)."""
    return (
        pl.col("finance_lease_status").fill_null("") == "not_stated",
        pl.lit(C.INPUT_EXCLUDES.value),
        pl.concat_str(
            pl.lit("total_debt leaves out a finance lease (the filing doesn't say where it's "
                   "presented): "),
            pl.col("finance_lease_evidence").fill_null(""),
        ),
    )  # fmt: skip


def result(
    value: pl.Expr,
    inputs: Sequence[In],
    guards: Sequence[Guard] = (),
    infos: Sequence[Info] = (),
) -> MetricExprs:
    """Value with null reasons; see the module docstring for precedence."""
    cases: list[tuple[pl.Expr, pl.Expr, pl.Expr]] = []  # condition, code, message
    nulls: list[pl.Expr] = []
    for tier in INPUT_PRECEDENCE:
        codes = sorted(c.value for c in tier)
        cases += [(i.value.is_null() & i.code.is_in(codes), i.code, i.message) for i in inputs]
    for i in inputs:
        cases.append((i.value.is_null(), i.code, i.message))
        nulls.append(i.value.is_null())
    for g in guards:
        cases.append((g.when, pl.lit(g.code.value), _lit(g.message)))
        nulls.append(g.when)
    for info in infos:
        cases.append((info.when, pl.lit(info.code.value), _lit(info.message)))
    if any(i.item is LineItem.TOTAL_DEBT and i.slot is MRQ for i in inputs):
        cases.append(lease_not_counted())
    for i in inputs:  # an earlier metric that leaves out a lease (EV inside EV/EBIT) says so too
        if i.metric_id is not None:
            excludes = i.code == C.INPUT_EXCLUDES.value
            cases.append((excludes, i.code, pl.concat_str(pl.lit(f"{i.label}: "), i.message)))
    if inputs:
        derived = [
            pl.when(i.derived).then(
                pl.lit(i.label) if i.note is None else pl.coalesce(i.note, pl.lit(i.label))
            )
            for i in inputs
        ]
        joined = pl.concat_list(derived).list.drop_nulls().list.join(", ")
        cases.append((
            pl.any_horizontal(*(i.derived for i in inputs)),
            pl.lit(C.DERIVED_INPUT.value),
            pl.concat_str(pl.lit("uses derived input: "), joined),
        ))  # fmt: skip
    none = pl.lit(None, pl.String)
    is_null = pl.any_horizontal(*nulls) if nulls else pl.lit(False)
    return MetricExprs(
        value=pl.when(is_null).then(None).otherwise(value),
        code=first([(c, k) for c, k, _ in cases], none),
        message=first([(c, m) for c, _, m in cases], none),
        inputs=tuple(inputs),
    )


def ratio(num: In, den: In, *, guard_den: bool = True, extra: Sequence[In] = ()) -> MetricExprs:
    """num / den, null (NEGATIVE_DENOMINATOR) when den ≤ 0."""
    guards = [den_le_zero(den)] if guard_den else []
    return result(num.value / den.value, [num, den, *extra], guards)


def over(num: pl.Expr, num_inputs: Sequence[In], den: In) -> MetricExprs:
    """An expression over `den`, null (NEGATIVE_DENOMINATOR) when den ≤ 0."""
    return result(num / den.value, [*num_inputs, den], [den_le_zero(den)])


# --- registry ---------------------------------------------------------------------------------

MetricFn = Callable[[Params], MetricExprs]
REGISTRY: dict[str, MetricFn] = {}


def metric(metric_id: str) -> Callable[[MetricFn], MetricFn]:
    """Register the function computing `metric_id` (one per id; the registry test checks both
    ways against config/metrics.yaml)."""

    def deco(fn: MetricFn) -> MetricFn:
        if metric_id in REGISTRY:
            raise ValueError(f"metric {metric_id!r} registered twice")
        REGISTRY[metric_id] = fn
        return fn

    return deco


@dataclass(frozen=True)
class MetricResult:
    values: pl.Series
    codes: pl.Series
    messages: pl.Series


def evaluate(fn: MetricFn, frame: pl.DataFrame, params: Params) -> MetricResult:
    e = fn(params)
    out = frame.select(e.value.alias("v"), e.code.alias("c"), e.message.alias("m"))
    return MetricResult(out["v"], out["c"], out["m"])
