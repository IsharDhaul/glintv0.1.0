"""Run a screen: validate, compile, execute, then assemble the funnel, near misses, ranks and
result rows (steps 5–8). Reads `metrics_snapshot` and `metric_notes` only; computes no metrics.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import duckdb

from glint.contracts.api import (
    AsOf,
    CellNote,
    CellValue,
    FunnelStep,
    NearMiss,
    ResultRow,
    ScreenResponse,
)
from glint.contracts.enums import NoteCode, Sector
from glint.contracts.metrics import MetricRegistry, load_registry
from glint.contracts.screen import (
    CATEGORICAL_FIELDS,
    PCT_RANK_CMPS,
    VS_MEDIAN_CMPS,
    Condition,
    Group,
    LogicOp,
    RankMethod,
    Screen,
    SortDir,
    SortKey,
)
from glint.screen.compile import CompiledScreen, Leaf, compile_screen
from glint.screen.config import ScreenConfig, load_screen_config
from glint.screen.labels import node_label
from glint.screen.validate import check_screen

MAX_NEAR_MISSES = 25
RANK_SCORE = "rank_score"
_PARAM_RE = re.compile(r"\$(p\d+)\b")

Row = dict[str, Any]


@dataclass
class ScreenRun:
    response: ScreenResponse
    compiled: CompiledScreen


# --- build metadata ----------------------------------------------------------------------------


def build_meta(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(con.execute("SELECT key, value FROM build_meta").fetchall())


def registry_for_build(con: duckdb.DuckDBPyConnection) -> MetricRegistry:
    """Synthetic builds have a value for every metric, so every registry id counts as live."""
    return load_registry(treat_all_as_live=build_meta(con).get("synthetic") == "true")


def _as_of(meta: dict[str, str]) -> AsOf:
    f, p = meta.get("as_of_fundamentals"), meta.get("as_of_prices")
    return AsOf(
        fundamentals=datetime.fromisoformat(f) if f else None,
        prices=date.fromisoformat(p) if p else None,
    )


def _bound(sql: str, params: dict[str, Any]) -> dict[str, Any]:
    """The params a statement actually uses (DuckDB rejects unused named parameters)."""
    used = set(_PARAM_RE.findall(sql))
    return {k: v for k, v in params.items() if k in used}


# --- 5. funnel (sieve) -------------------------------------------------------------------------


def _funnel(
    compiled: CompiledScreen,
    agg: tuple[Any, ...],
    counts: tuple[int, int, int],
    registry: MetricRegistry,
) -> list[FunnelStep]:
    """`agg` is the `funnel_sql` row: n0, then (n_k, m_k) per step: survivors after step k,
    and rows step k removed that would pass if every null passed."""
    total, universe, universe_if_nulls_passed = counts
    steps = [
        FunnelStep(
            index=0,
            label="Universe",
            filter_path=None,
            remaining=universe,
            removed=total - universe,
            removed_missing=universe_if_nulls_passed - universe,
            binding=False,
        )
    ]
    alive = int(agg[0])
    for k, step in enumerate(compiled.steps):
        kept, removed_missing = int(agg[1 + 2 * k]), int(agg[2 + 2 * k])
        steps.append(
            FunnelStep(
                index=step.index,
                label=node_label(step.node, registry),
                filter_path=step.path,
                remaining=kept,
                removed=alive - kept,
                removed_missing=removed_missing,
                binding=False,
            )
        )
        alive = kept
    filter_steps = steps[1:]
    if filter_steps and (top := max(s.removed for s in filter_steps)) > 0:
        first = next(s for s in filter_steps if s.removed == top)
        first.binding = True
    return steps


# --- 6. near misses ----------------------------------------------------------------------------


def _leaf_count(node: Condition | Group) -> int:
    return 1 if isinstance(node, Condition) else sum(_leaf_count(c) for c in node.children)


def _split(node: Group, leaves: list[Leaf]) -> list[tuple[Condition | Group, list[Leaf]]]:
    """Each child with its own leaves (leaves are in depth-first order)."""
    out: list[tuple[Condition | Group, list[Leaf]]] = []
    i = 0
    for child in node.children:
        n = _leaf_count(child)
        out.append((child, leaves[i : i + n]))
        i += n
    return out


def _node_ok(node: Condition | Group, leaves: list[Leaf], row: Row) -> bool:
    if isinstance(node, Condition):
        return bool(row[f"l{leaves[0].index}_ok"])
    results = [_node_ok(child, sub, row) for child, sub in _split(node, leaves)]
    return all(results) if node.op is LogicOp.AND else any(results)


def _explain_failure(
    node: Condition | Group, leaves: list[Leaf], row: Row
) -> tuple[Leaf, float | None]:
    """For a failed node, the leaf that explains the failure and its distance.

    OR fails only if every child fails: report the closest child. AND fails if any child fails:
    report the failing child furthest away (an unknown distance counts as furthest)."""
    if isinstance(node, Condition):
        d = row[f"l{leaves[0].index}_d"]
        return leaves[0], (None if d is None else float(d))
    failing = [
        _explain_failure(child, sub, row)
        for child, sub in _split(node, leaves)
        if not _node_ok(child, sub, row)
    ]
    if node.op is LogicOp.OR:
        known = [(lf, d) for lf, d in failing if d is not None]
        return min(known, key=lambda t: t[1] or 0.0) if known else failing[0]
    unknown = [(lf, d) for lf, d in failing if d is None]
    return unknown[0] if unknown else max(failing, key=lambda t: t[1] or 0.0)


def _near_misses(
    con: duckdb.DuckDBPyConnection,
    compiled: CompiledScreen,
    rows: list[Row],
    registry: MetricRegistry,
    config: ScreenConfig,
) -> list[NearMiss]:
    out: list[tuple[float | None, str, Leaf, NearMiss]] = []
    for row in rows:
        failed = [s for s in compiled.steps if not row[f"s{s.index}_ok"]]
        if len(failed) != 1:
            continue
        step = failed[0]
        step_leaves = [lf for lf in compiled.leaves if lf.step == step.index - 1]
        leaf, distance = _explain_failure(step.node, step_leaves, row)
        value, threshold = _value_threshold(leaf, row)
        out.append(
            (
                distance,
                row["ticker"],
                leaf,
                NearMiss(
                    cik=row["cik"],
                    ticker=row["ticker"],
                    name=row["name"],
                    sector=Sector(row["sector"]),
                    failed_filter_path=step.path,
                    failed_label=node_label(step.node, registry),
                    metric=leaf.cond.metric,
                    cmp=leaf.cond.cmp,
                    value=value,
                    threshold=threshold,
                    distance=distance,
                ),
            )
        )
    out.sort(key=lambda t: (t[0] is None, t[0] or 0.0, t[1]))
    shown = out[:MAX_NEAR_MISSES]
    by_cik = {r["cik"]: r for r in rows}
    null_leaves = [(lf, nm) for _, _, lf, nm in shown if by_cik[nm.cik][f"l{lf.index}_v"] is None]
    stored = _notes(
        con, [nm.cik for _, nm in null_leaves], [lf.cond.metric for lf, _ in null_leaves]
    )
    for lf, nm in null_leaves:
        nm.note = _near_miss_note(lf, by_cik[nm.cik], stored.get(nm.cik, {}), config)
    return [nm for _, _, _, nm in shown]


def _near_miss_note(
    leaf: Leaf, row: Row, stored: dict[str, CellNote], config: ScreenConfig
) -> CellNote:
    """Why a near miss's compared value is null: the metric's own reason, a small sector, or a
    sector median ≤ 0 under a ratio vs-median filter."""
    metric = leaf.cond.metric
    if row[metric] is None:
        return stored.get(metric) or CellNote(
            code=NoteCode.MISSING_INPUT, message=f"{metric} is missing; no reason recorded."
        )
    if row.get(f"sp_{metric}"):
        return CellNote(
            code=NoteCode.SMALL_PEER_GROUP,
            message=f"Fewer than {config.small_peer_group_min} {metric} values in "
            f"{row['sector']}: no sector percentile or median.",
        )
    return CellNote(
        code=NoteCode.NEGATIVE_DENOMINATOR,
        message=f"{row['sector']} median {metric} is ≤ 0: a ratio to it isn't meaningful.",
    )


def _value_threshold(leaf: Leaf, row: Row) -> tuple[CellValue, CellValue | list[CellValue]]:
    """Percentile filters report the company's percentile against the percentile threshold;
    vs-median filters report the raw value against the raw value the median implies."""
    cond = leaf.cond
    if cond.cmp in PCT_RANK_CMPS:
        return row[f"l{leaf.index}_v"], cond.value  # pyright: ignore[reportReturnType]
    if cond.cmp in VS_MEDIAN_CMPS:
        return row[cond.metric], row[f"l{leaf.index}_t"]
    value: CellValue = row[cond.metric]
    if isinstance(cond.value, list):
        return value, list(cond.value)
    return value, cond.value


# --- 7. ranking --------------------------------------------------------------------------------


@dataclass
class _Score:
    score: float | None
    contributions: dict[str, float | None]
    note: CellNote | None


def _score_row(screen: Screen, compiled: CompiledScreen, row: Row, tol: float) -> _Score:
    rank = screen.rank
    assert rank is not None
    specs = compiled.factors
    raw = {s.metric: row[f"f_{s.metric}"] for s in specs}
    present = [s for s in specs if raw[s.metric] is not None]
    total_w = sum(s.weight for s in specs)
    present_w = sum(s.weight for s in present)
    required = 1.0 if rank.method is RankMethod.RANK_SUM else rank.min_factor_coverage
    if present_w / total_w < required - tol:
        missing = [s.metric for s in specs if raw[s.metric] is None]
        small = any(row.get(f"sp_{m}") for m in missing)
        code = NoteCode.SMALL_PEER_GROUP if small else NoteCode.MISSING_INPUT
        reason = "fewer than the minimum peers in its sector" if small else "missing"
        message = f"Factor coverage {present_w / total_w:.0%} < {required:.0%}: " + (
            f"{', '.join(missing)} {reason}."
        )
        return _Score(None, dict.fromkeys(raw), CellNote(code=code, message=message))
    contributions: dict[str, float | None] = dict.fromkeys(raw)
    if rank.method is RankMethod.PERCENTILE_COMPOSITE:
        # Weights re-normalized over present factors; contributions sum to the score.
        for s in present:
            contributions[s.metric] = s.weight / present_w * float(raw[s.metric])
    else:
        # Weighted rank sum; equal weights give Greenblatt's plain sum of ranks.
        mean_w = total_w / len(specs)
        for s in present:
            contributions[s.metric] = s.weight / mean_w * float(raw[s.metric])
    score = sum(c for c in contributions.values() if c is not None)
    return _Score(score, contributions, None)


def _rank_positions(
    screen: Screen, passing: list[Row], scores: dict[str, _Score]
) -> dict[str, int]:
    """1 = best; ties broken by ticker ascending. Unscored rows get no rank."""
    assert screen.rank is not None
    sign = -1.0 if screen.rank.method is RankMethod.PERCENTILE_COMPOSITE else 1.0
    scored = [r for r in passing if scores[r["cik"]].score is not None]
    scored.sort(key=lambda r: (sign * float(scores[r["cik"]].score or 0.0), r["ticker"]))
    return {r["cik"]: i for i, r in enumerate(scored, start=1)}


# --- 8. results --------------------------------------------------------------------------------


def _sort_rows(screen: Screen, passing: list[Row], positions: dict[str, int] | None) -> list[Row]:
    """`sort.by`, then each `sort.then` key, then ticker ascending. Nulls go last for every key.
    `rank_score` sorts by rank position (desc = best first); unranked rows count as null.
    Omitted sort: rank_score desc when ranked, else ticker asc."""
    rows = sorted(passing, key=lambda r: r["ticker"])
    sort = screen.sort
    if sort is None:
        if positions is None:
            return rows
        keys = [SortKey(by=RANK_SCORE, dir=SortDir.DESC)]
    else:
        keys = sort.all_keys()

    def value(r: Row, by: str) -> Any:
        if by == RANK_SCORE:
            pos = (positions or {}).get(r["cik"])
            return None if pos is None else -pos  # higher = better, as for desc metrics
        return r[by]

    # Stable sorts from the last key to the first, each within the order the later keys left.
    # (`reverse=True` keeps equal values in their existing order.)
    for key in reversed(keys):
        pairs = [(value(r, key.by), r) for r in rows]
        present = [(v, r) for v, r in pairs if v is not None]
        present.sort(key=lambda p: p[0], reverse=key.dir is SortDir.DESC)
        rows = [r for _, r in present] + [r for v, r in pairs if v is None]
    return rows


def _notes(
    con: duckdb.DuckDBPyConnection, ciks: list[str], columns: list[str]
) -> dict[str, dict[str, CellNote]]:
    metric_cols = [c for c in columns if c not in CATEGORICAL_FIELDS]
    out: dict[str, dict[str, CellNote]] = {}
    if not ciks or not metric_cols:
        return out
    rows = con.execute(
        "SELECT cik, metric_id, code, message FROM metric_notes "
        "WHERE list_contains($ciks, cik) AND list_contains($metrics, metric_id)",
        {"ciks": ciks, "metrics": metric_cols},
    ).fetchall()
    for cik, metric_id, code, message in rows:
        out.setdefault(cik, {})[metric_id] = CellNote(code=NoteCode(code), message=message)
    return out


def _page_values(
    con: duckdb.DuckDBPyConnection, compiled: CompiledScreen, ciks: list[str]
) -> dict[str, Row]:
    """Requested columns for the result page only, straight from the snapshot."""
    if not ciks:
        return {}
    names = list(dict.fromkeys(["cik", *compiled.columns]))
    rows = con.execute(compiled.page_sql, {"ciks": ciks}).fetchall()
    return {r[0]: dict(zip(names, r, strict=True)) for r in rows}


def _one(con: duckdb.DuckDBPyConnection, query_sql: str, params: dict[str, Any]) -> tuple[Any, ...]:
    row = con.execute(query_sql, _bound(query_sql, params)).fetchone()
    assert row is not None, "aggregate queries return one row"
    return row


def _cell(value: Any) -> CellValue:
    return value if value is None or isinstance(value, bool | str) else float(value)


def run_screen(
    con: duckdb.DuckDBPyConnection,
    screen: Screen,
    registry: MetricRegistry,
    config: ScreenConfig | None = None,
) -> ScreenRun:
    """Validate and run `screen` on the build behind `con` (read-only is enough).

    Raises `InvalidScreenError` (422) when the screen doesn't fit the registry."""
    config = config or load_screen_config()
    warnings = check_screen(screen, registry)
    compiled = compile_screen(screen, registry, config)
    meta = build_meta(con)

    counts_row = _one(con, compiled.counts_sql, compiled.params)
    counts = (int(counts_row[0]), int(counts_row[1]), int(counts_row[2]))
    cur = con.execute(compiled.rows_sql, _bound(compiled.rows_sql, compiled.params))
    rows = [dict(zip(compiled.narrow_columns, r, strict=True)) for r in cur.fetchall()]
    # The funnel counts ride along on every row; with no rows, ask for them directly.
    agg = (
        tuple(rows[0][f"w_{name}"] for name in compiled.funnel_columns)
        if rows
        else _one(con, compiled.funnel_sql, compiled.params)
    )
    funnel = _funnel(compiled, agg, counts, registry)

    passing = [r for r in rows if all(r[f"s{s.index}_ok"] for s in compiled.steps)]
    near = _near_misses(con, compiled, rows, registry, config) if screen.near_misses else []

    scores: dict[str, _Score] = {}
    positions: dict[str, int] | None = None
    if screen.rank is not None:
        tol = config.float_tolerance
        scores = {r["cik"]: _score_row(screen, compiled, r, tol) for r in passing}
        positions = _rank_positions(screen, passing, scores)

    page = _sort_rows(screen, passing, positions)[: screen.limit]
    page_ciks = [r["cik"] for r in page]
    notes = _notes(con, page_ciks, compiled.columns)
    page_values = _page_values(con, compiled, page_ciks)
    results: list[ResultRow] = []
    for r in page:
        sc = scores.get(r["cik"])
        # Values in the order the screen asked for them (rank_score included).
        values: dict[str, CellValue] = {
            c: (sc.score if sc else None) if c == RANK_SCORE else _cell(page_values[r["cik"]][c])
            for c in screen.columns
        }
        row_notes = dict(notes.get(r["cik"], {}))
        if RANK_SCORE in screen.columns and sc is not None and sc.note is not None:
            row_notes[RANK_SCORE] = sc.note
        results.append(
            ResultRow(
                cik=r["cik"],
                ticker=r["ticker"],
                name=r["name"],
                sector=Sector(r["sector"]),
                rank=positions.get(r["cik"]) if positions is not None else None,
                rank_score=sc.score if sc else None,
                factor_contributions=sc.contributions if sc else {},
                values=values,
                notes=row_notes,
            )
        )

    response = ScreenResponse(
        build_id=meta.get("build_id"),
        as_of=_as_of(meta),
        universe_count=counts[1],
        funnel=funnel,
        total=len(passing),
        results=results,
        near_misses=near,
        warnings=warnings,
    )
    return ScreenRun(response=response, compiled=compiled)
