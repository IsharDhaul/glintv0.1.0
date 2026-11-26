"""Screen → one DuckDB query over `metrics_snapshot` (steps 2–4).

The query has four layers:

1. `u`: the universe (`WHERE` built from the `universe` block).
2. `s`: relative stats from window functions **over `u`**: percentiles, sector medians and
   peer counts. They exist only after universe filters, so changing the universe changes them.
3. `l`: per filter leaf, the value it compares (raw, percentile, or gap to the sector median)
   and, for vs-median leaves, the raw threshold that implies.
4. `e`: per leaf `ok` (passes, with its missing policy), `opt` (passes if every null passed)
   and `d` (near-miss distance); per top-level step, `ok`/`opt` composed through AND/OR groups.

Sieve, near misses and ranking are assembled from the rows in `glint.screen.engine`.
"""

from dataclasses import dataclass, field
from typing import Any

from glint.contracts.enums import Better, Unit
from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import (
    CATEGORICAL_FIELDS,
    PCT_RANK_CMPS,
    SPECIAL_COLUMNS,
    VS_MEDIAN_CMPS,
    Comparator,
    Condition,
    Group,
    LogicOp,
    MissingPolicy,
    RankMethod,
    Screen,
    Within,
)
from glint.screen.config import ScreenConfig
from glint.screen.sql import SNAPSHOT_TABLE, AllowList, Params, alias, column_key

ROW_KEYS = ("cik", "ticker", "name", "sector")
_DIFF_UNITS = frozenset({Unit.FRAC, Unit.PP})  # vs-median is a difference for these, else ratio


@dataclass(frozen=True)
class Leaf:
    index: int
    step: int  # top-level child it belongs to
    path: list[str | int]
    cond: Condition
    unit: Unit


@dataclass(frozen=True)
class Step:
    index: int  # 1-based, as in the funnel (0 is the universe)
    path: list[str | int]
    node: Condition | Group


@dataclass(frozen=True)
class FactorSpec:
    metric: str
    weight: float
    better: Better


@dataclass
class CompiledScreen:
    """`sql` evaluates every universe row (tests, --explain). The engine runs `counts_sql`,
    `funnel_sql` and `rows_sql` (passing rows + near-miss candidates only), then `page_sql`
    with `$ciks` bound to the result page. All share `params`."""

    sql: str
    counts_sql: str
    funnel_sql: str
    rows_sql: str
    page_sql: str
    params: dict[str, Any]
    leaves: list[Leaf]
    steps: list[Step]
    factors: list[FactorSpec]
    columns: list[str]  # requested value columns (not rank_score)
    row_columns: list[str] = field(default_factory=list[str])  # columns of `sql`
    narrow_columns: list[str] = field(default_factory=list[str])  # columns of `rows_sql`
    funnel_columns: list[str] = field(default_factory=list[str])  # columns of `funnel_sql`


def _unit(metric: str, registry: MetricRegistry) -> Unit:
    if metric in CATEGORICAL_FIELDS:
        return CATEGORICAL_FIELDS[metric]
    m = registry.get(metric)
    assert m is not None, "screens are validated before compiling"
    return m.unit


class _Compiler:
    def __init__(self, screen: Screen, registry: MetricRegistry, config: ScreenConfig) -> None:
        self.screen = screen
        self.registry = registry
        self.config = config
        self.allow = AllowList.for_registry(registry)
        self.p = Params()
        self.stats: dict[str, str] = {}  # alias → expression, in insertion order
        self.leaves: list[Leaf] = []
        self.steps: list[Step] = []

    # --- 2. universe ---------------------------------------------------------------------

    def universe_where(self, *, optimistic: bool = False) -> str:
        """The universe `WHERE`. A null never satisfies a numeric bound (a company without a
        market cap isn't "≥ $1B"); `optimistic` lets nulls pass, to count those exclusions."""
        u, c, p = self.screen.universe, self.allow.ident, self.p.bind
        exchange_sql = f"list_contains({p([e.value for e in u.exchanges])}, {c('exchange')})"
        # A company with no known exchange is out of the universe, but counted as missing data.
        where = [f"({c('exchange')} IS NULL OR {exchange_sql})" if optimistic else exchange_sql]
        if u.sectors_include:
            where.append(f"list_contains({p([s.value for s in u.sectors_include])}, {c('sector')})")
        if u.sectors_exclude:
            excluded_sql = p([s.value for s in u.sectors_exclude])
            where.append(f"NOT list_contains({excluded_sql}, {c('sector')})")
        if u.exclude_kinds:
            where.append(f"NOT list_contains({p([k.value for k in u.exclude_kinds])}, {c('kind')})")
        if not u.include_foreign_filers:
            where.append(f"NOT {c('is_foreign_filer')}")
        if not u.include_stale:
            where.append(f"NOT {c('is_stale')}")
        if not u.include_no_facts:
            where.append(c("has_facts"))
        bounds = (
            ("market_cap", ">=", u.market_cap_min),
            ("market_cap", "<=", u.market_cap_max),
            ("avg_dollar_volume_3m", ">=", u.avg_dollar_volume_min),
            ("days_since_filing", "<=", u.max_days_since_filing),
        )
        for col, op_sql, bound in bounds:
            if bound is None:
                continue
            col_sql = c(col)
            test_sql = f"{col_sql} {op_sql} {p(bound)}"
            where.append(f"({col_sql} IS NULL OR {test_sql})" if optimistic else test_sql)
        return "\n      AND ".join(where)

    def universe_counts_sql(self) -> str:
        """Snapshot rows, rows in the universe, rows only a null bound kept out."""
        strict_sql = self.universe_where()
        optimistic_sql = self.universe_where(optimistic=True)
        return (
            f"SELECT count(*) AS total,\n"
            f"       count(*) FILTER (WHERE {strict_sql}) AS universe,\n"
            f"       count(*) FILTER (WHERE {optimistic_sql}) AS universe_if_nulls_passed\n"
            f"FROM {SNAPSHOT_TABLE}"
        )

    # --- 3. relative stats ---------------------------------------------------------------

    def _peer_count(self, metric: str) -> str:
        """Non-null values of `metric` in the company's sector, within the universe."""
        name = alias("n_s_", metric)
        if name not in self.stats:
            x_sql, sector_sql = self.allow.ident(metric), self.allow.ident("sector")
            self.stats[name] = f"count({x_sql}) OVER (PARTITION BY {sector_sql})"
        return name

    def _small_peer_sql(self, metric: str) -> str:
        n_sql = self._peer_count(metric)
        return f"{n_sql} < {self.p.bind(self.config.small_peer_group_min)}"

    def percentile(self, metric: str, within: Within, *, ascending: bool = True) -> str:
        """percent_rank() over non-null values in scope; null for nulls and small sectors."""
        prefix = ("pr_" if ascending else "prd_") + ("s_" if within is Within.SECTOR else "u_")
        name = alias(prefix, metric)
        if name in self.stats:
            return name
        x_sql = self.allow.ident(metric)
        # Partitioning by `x IS NULL` keeps nulls out of the non-null window.
        part_sql = f"({x_sql} IS NULL)"
        null_sql = f"{x_sql} IS NULL"
        if within is Within.SECTOR:
            part_sql = f"{part_sql}, {self.allow.ident('sector')}"
            null_sql = f"{null_sql} OR {self._small_peer_sql(metric)}"
        dir_sql = "ASC" if ascending else "DESC"
        self.stats[name] = (
            f"CASE WHEN {null_sql} THEN NULL "
            f"ELSE percent_rank() OVER (PARTITION BY {part_sql} ORDER BY {x_sql} {dir_sql}) END"
        )
        return name

    def ordinal_rank(self, metric: str, within: Within, *, higher_first: bool) -> str:
        """rank() with 1 = best, over non-null values in scope (rank_sum)."""
        name = alias("or_s_" if within is Within.SECTOR else "or_u_", metric)
        if name in self.stats:
            return name
        x_sql = self.allow.ident(metric)
        part_sql = f"({x_sql} IS NULL)"
        null_sql = f"{x_sql} IS NULL"
        if within is Within.SECTOR:
            part_sql = f"{part_sql}, {self.allow.ident('sector')}"
            null_sql = f"{null_sql} OR {self._small_peer_sql(metric)}"
        dir_sql = "DESC" if higher_first else "ASC"
        self.stats[name] = (
            f"CASE WHEN {null_sql} THEN NULL "
            f"ELSE rank() OVER (PARTITION BY {part_sql} ORDER BY {x_sql} {dir_sql}) END"
        )
        return name

    def small_peer_flag(self, metric: str) -> str:
        name = alias("sp_", metric)
        if name not in self.stats:
            self.stats[name] = self._small_peer_sql(metric)
        return name

    def sector_median(self, metric: str) -> str:
        """Sector median over the universe; null when the sector has too few values."""
        name = alias("med_", metric)
        if name not in self.stats:
            x_sql, sector_sql = self.allow.ident(metric), self.allow.ident("sector")
            small_sql = self._small_peer_sql(metric)
            self.stats[name] = (
                f"CASE WHEN {small_sql} THEN NULL "
                f"ELSE median({x_sql}) OVER (PARTITION BY {sector_sql}) END"
            )
        return name

    # --- 4. filters ----------------------------------------------------------------------

    def collect(self) -> None:
        for i, child in enumerate(self.screen.filters.children):
            path: list[str | int] = ["filters", "children", i]
            self.steps.append(Step(index=i + 1, path=path, node=child))
            self._collect_node(child, i, path)

    def _collect_node(self, node: Condition | Group, step: int, path: list[str | int]) -> None:
        if isinstance(node, Group):
            for j, child in enumerate(node.children):
                self._collect_node(child, step, [*path, "children", j])
            return
        leaf = Leaf(len(self.leaves), step, path, node, _unit(node.metric, self.registry))
        self.leaves.append(leaf)

    def leaf_value_sql(self, leaf: Leaf) -> tuple[str, str | None]:
        """(value compared, raw threshold for vs-median leaves)."""
        cond, x_sql = leaf.cond, self.allow.ident(leaf.cond.metric)
        if _sector_scoped(cond):
            self.small_peer_flag(cond.metric)  # near misses explain a null percentile/median
        if cond.cmp in PCT_RANK_CMPS:
            return self.percentile(cond.metric, cond.within or Within.UNIVERSE), None
        if cond.cmp in VS_MEDIAN_CMPS:
            med_sql = self.sector_median(cond.metric)
            t_sql = self.p.bind(cond.value)
            if leaf.unit in _DIFF_UNITS:
                return f"{x_sql} - {med_sql}", f"{med_sql} + {t_sql}"
            # A ratio to a median ≤ 0 has no meaning: it reads as missing.
            return (
                f"CASE WHEN {med_sql} > 0 THEN {x_sql} / {med_sql} END",
                f"CASE WHEN {med_sql} > 0 THEN {med_sql} * {t_sql} END",
            )
        return x_sql, None

    def leaf_test_sql(self, leaf: Leaf) -> str:
        """The comparison on `l<i>_v`; null when the value is null."""
        cond, c, b = leaf.cond, leaf.cond.cmp, self.p.bind
        v_sql = alias(f"l{leaf.index}_", "v")
        tol_sql = b(self.config.float_tolerance)
        if c in (Comparator.GT,):
            return f"{v_sql} > {b(cond.value)} + {tol_sql}"
        if c in (Comparator.GTE, Comparator.PCT_RANK_GTE, Comparator.VS_SECTOR_MEDIAN_GTE):
            return f"{v_sql} >= {b(cond.value)} - {tol_sql}"
        if c is Comparator.LT:
            return f"{v_sql} < {b(cond.value)} - {tol_sql}"
        if c in (Comparator.LTE, Comparator.PCT_RANK_LTE, Comparator.VS_SECTOR_MEDIAN_LTE):
            return f"{v_sql} <= {b(cond.value)} + {tol_sql}"
        if c is Comparator.BETWEEN:
            assert isinstance(cond.value, list)
            lo, hi = cond.value
            return f"{v_sql} BETWEEN {b(lo)} - {tol_sql} AND {b(hi)} + {tol_sql}"
        if c is Comparator.EQ:
            return f"{v_sql} = {b(cond.value)}"
        if c is Comparator.NEQ:
            return f"{v_sql} <> {b(cond.value)}"
        if c is Comparator.IN:
            return f"list_contains({b(cond.value)}, {v_sql})"
        if c is Comparator.IS_NULL:
            return f"{v_sql} IS NULL"
        return f"{v_sql} IS NOT NULL"

    def leaf_distance_sql(self, leaf: Leaf) -> str:
        """|value − threshold| / |threshold| (absolute gap when the threshold is 0), or the
        percentile gap. Null for categorical and null tests."""
        cond, b = leaf.cond, self.p.bind
        if cond.cmp in PCT_RANK_CMPS:
            v_sql = alias(f"l{leaf.index}_", "v")
            return f"abs({v_sql} - {b(cond.value)})"
        if cond.cmp in VS_MEDIAN_CMPS:
            x_sql, t_sql = self.allow.ident(cond.metric), alias(f"l{leaf.index}_", "t")
        elif cond.cmp is Comparator.BETWEEN:
            assert isinstance(cond.value, list)
            lo, hi = cond.value
            x_sql = self.allow.ident(cond.metric)
            t_sql = f"(CASE WHEN {x_sql} < {b(lo)} THEN {b(lo)} ELSE {b(hi)} END)"
        elif cond.cmp in (Comparator.GT, Comparator.GTE, Comparator.LT, Comparator.LTE):
            x_sql, t_sql = self.allow.ident(cond.metric), b(cond.value)
        else:
            return "NULL::DOUBLE"
        return f"abs({x_sql} - {t_sql}) / coalesce(nullif(abs({t_sql}), 0), 1)"

    def node_sql(self, node: Condition | Group, path_leaves: list[Leaf], kind: str) -> str:
        """`ok` or `opt` of a node, composed from its leaves' columns."""
        if isinstance(node, Condition):
            leaf = path_leaves.pop(0)
            return alias(f"l{leaf.index}_", kind)
        op_sql = " AND " if node.op is LogicOp.AND else " OR "
        parts = [self.node_sql(child, path_leaves, kind) for child in node.children]
        joined_sql = op_sql.join(parts)
        return f"({joined_sql})"

    # --- ranking stats -------------------------------------------------------------------

    def factor_specs(self) -> list[FactorSpec]:
        rank = self.screen.rank
        if rank is None:
            return []
        out: list[FactorSpec] = []
        for f in rank.factors:
            m = self.registry.get(f.metric)
            assert m is not None
            out.append(FactorSpec(f.metric, f.weight, m.better))
            higher = m.better is Better.HIGHER
            if rank.method is RankMethod.PERCENTILE_COMPOSITE:
                # Direction-aware: the best value gets percentile 1.
                self.percentile(f.metric, rank.within, ascending=higher)
            else:
                self.ordinal_rank(f.metric, rank.within, higher_first=higher)
            if rank.within is Within.SECTOR:
                self.small_peer_flag(f.metric)
        return out

    def factor_column(self, spec: FactorSpec) -> str:
        rank = self.screen.rank
        assert rank is not None
        higher = spec.better is Better.HIGHER
        if rank.method is RankMethod.PERCENTILE_COMPOSITE:
            return self.percentile(spec.metric, rank.within, ascending=higher)
        return self.ordinal_rank(spec.metric, rank.within, higher_first=higher)

    # --- assembly ------------------------------------------------------------------------

    def compile(self) -> CompiledScreen:
        where_sql = self.universe_where()
        counts_sql = self.universe_counts_sql()
        self.collect()
        leaf_values = [(leaf, *self.leaf_value_sql(leaf)) for leaf in self.leaves]
        factors = self.factor_specs()
        # Carry only the columns the screen touches: window operators materialize every column.
        needed = dict.fromkeys(
            [*ROW_KEYS]
            + [c for c in self.screen.columns if c not in SPECIAL_COLUMNS]
            + [leaf.cond.metric for leaf in self.leaves]
            + [f.metric for f in factors]
        )
        u_cols_sql = ", ".join(self.allow.ident(col) for col in needed)

        s_sql = _layer(
            "u", [f"{expr_sql} AS {name_sql}" for name_sql, expr_sql in self.stats.items()]
        )

        l_parts: list[str] = []
        for leaf, value_sql, thr_sql in leaf_values:
            l_parts.append(f"{value_sql} AS {alias(f'l{leaf.index}_', 'v')}")
            if thr_sql is not None:
                l_parts.append(f"{thr_sql} AS {alias(f'l{leaf.index}_', 't')}")
        l_sql = _layer("s", l_parts)

        e_parts: list[str] = []
        for leaf in self.leaves:
            v_sql, test_sql = alias(f"l{leaf.index}_", "v"), self.leaf_test_sql(leaf)
            ok_sql, opt_sql = alias(f"l{leaf.index}_", "ok"), alias(f"l{leaf.index}_", "opt")
            if leaf.cond.cmp in (Comparator.IS_NULL, Comparator.NOT_NULL):
                # `not_null` removes a company only for missing data, so it would pass if
                # nulls passed; `is_null` removes companies that *have* data.
                opt_test_sql = "TRUE" if leaf.cond.cmp is Comparator.NOT_NULL else test_sql
                e_parts += [f"{test_sql} AS {ok_sql}", f"{opt_test_sql} AS {opt_sql}"]
            else:
                policy_sql = "TRUE" if leaf.cond.missing is MissingPolicy.PASS else "FALSE"
                e_parts += [
                    f"CASE WHEN {v_sql} IS NULL THEN {policy_sql} ELSE {test_sql} END AS {ok_sql}",
                    f"CASE WHEN {v_sql} IS NULL THEN TRUE ELSE {test_sql} END AS {opt_sql}",
                ]
            dist_sql = self.leaf_distance_sql(leaf)
            e_parts.append(f"{dist_sql} AS {alias(f'l{leaf.index}_', 'd')}")
        e_sql = _layer("l", e_parts)

        f_parts: list[str] = []
        for step in self.steps:
            step_leaves = [leaf for leaf in self.leaves if leaf.step == step.index - 1]
            for kind in ("ok", "opt"):
                node_sql = self.node_sql(step.node, list(step_leaves), kind)
                f_parts.append(f"{node_sql} AS {alias(f's{step.index}_', kind)}")
        f_sql = _layer("e", f_parts)

        cte_sql = (
            f"WITH u AS (\n    SELECT {u_cols_sql}\n    FROM {SNAPSHOT_TABLE}\n"
            f"    WHERE {where_sql}\n),\n"
            f"s AS (\n    {s_sql}\n),\n"
            f"l AS (\n    {l_sql}\n),\n"
            f"e AS (\n    {e_sql}\n),\n"
            f"f AS (\n    {f_sql}\n)\n"
        )
        order_sql = self.allow.ident("ticker")
        columns = [col for col in self.screen.columns if col not in SPECIAL_COLUMNS]

        # Full evaluation, one row per universe company (tests and --explain).
        full = self._identity()
        for col in columns:
            full[col] = self.allow.ident(col)
        for leaf in self.leaves:
            full |= self._leaf_columns(leaf, with_opt=True)
        for step in self.steps:
            for kind in ("ok", "opt"):
                full[column_key(f"s{step.index}_", kind)] = alias(f"s{step.index}_", kind)
        full |= self._factor_columns(factors)
        sql = f"{cte_sql}SELECT {_projection(full)}\nFROM f\nORDER BY {order_sql}"

        narrow, rows_sql = self._rows_query(cte_sql, factors, order_sql)
        funnel = self._funnel_counts()
        funnel_sql = f"{cte_sql}SELECT {_projection(funnel)}\nFROM f"

        page_cols_sql = ", ".join(self.allow.ident(col) for col in dict.fromkeys(["cik", *columns]))
        cik_sql = self.allow.ident("cik")
        page_sql = (
            f"SELECT {page_cols_sql}\nFROM {SNAPSHOT_TABLE}\nWHERE list_contains($ciks, {cik_sql})"
        )
        return CompiledScreen(
            sql=sql,
            counts_sql=counts_sql,
            funnel_sql=funnel_sql,
            rows_sql=rows_sql,
            page_sql=page_sql,
            params=dict(self.p.values),
            leaves=self.leaves,
            steps=self.steps,
            factors=factors,
            columns=columns,
            row_columns=list(full),
            narrow_columns=list(narrow),
            funnel_columns=list(funnel),
        )

    def _funnel_counts(self) -> dict[str, str]:
        """n0, then per step k: survivors after step k (`n<k>`) and rows step k removed that
        would pass if every null passed (`m<k>`)."""
        out = {"n0": "count(*)"}
        prefix_sql = "TRUE"
        for step in self.steps:
            ok_sql, opt_sql = alias(f"s{step.index}_", "ok"), alias(f"s{step.index}_", "opt")
            removed_missing_sql = f"{prefix_sql} AND NOT {ok_sql} AND {opt_sql}"
            prefix_sql = f"{prefix_sql} AND {ok_sql}"
            out[column_key("n", step.index)] = f"count(*) FILTER (WHERE {prefix_sql})"
            out[column_key("m", step.index)] = f"count(*) FILTER (WHERE {removed_missing_sql})"
        return out

    def _rows_query(
        self, cte_sql: str, factors: list[FactorSpec], order_sql: str
    ) -> tuple[dict[str, str], str]:
        """Rows that pass, plus near-miss candidates (fail exactly one step), each carrying the
        funnel counts from a one-row aggregate over every universe row. `f` is materialized,
        so the screen is evaluated once for both."""
        narrow = self._identity()
        if self.screen.sort is not None:
            for key in self.screen.sort.all_keys():
                if key.by not in SPECIAL_COLUMNS:
                    narrow[key.by] = self.allow.ident(key.by)
        if self.screen.near_misses:
            for leaf in self.leaves:
                narrow |= self._leaf_columns(leaf, with_opt=False)
        for step in self.steps:
            narrow[column_key(f"s{step.index}_", "ok")] = alias(f"s{step.index}_", "ok")
        narrow |= self._factor_columns(factors)
        counts = {
            column_key("w_", name): expr_sql for name, expr_sql in self._funnel_counts().items()
        }
        agg_sql = _projection(counts)
        narrow |= {name: alias("", name) for name in counts}
        fails = [f"(NOT {alias(f's{step.index}_', 'ok')})::INTEGER" for step in self.steps]
        fails_sql = " + ".join(fails) or "0"
        max_fails_sql = "1" if self.screen.near_misses else "0"
        materialized_sql = cte_sql.rstrip().replace("f AS (", "f AS MATERIALIZED (", 1)
        rows_sql = (
            f"{materialized_sql},\nagg AS (\n    SELECT {agg_sql}\n    FROM f\n)\n"
            f"SELECT {_projection(narrow)}\nFROM f CROSS JOIN agg\n"
            f"WHERE {fails_sql} <= {max_fails_sql}\nORDER BY {order_sql}"
        )
        return narrow, rows_sql

    def _identity(self) -> dict[str, str]:
        return {key: self.allow.ident(key) for key in ROW_KEYS}

    def _leaf_columns(self, leaf: Leaf, *, with_opt: bool) -> dict[str, str]:
        out = {leaf.cond.metric: self.allow.ident(leaf.cond.metric)}
        kinds = ["v", "ok", "d"] + (["opt"] if with_opt else [])
        if leaf.cond.cmp in VS_MEDIAN_CMPS:
            kinds.append("t")
        for kind in kinds:
            out[column_key(f"l{leaf.index}_", kind)] = alias(f"l{leaf.index}_", kind)
        if _sector_scoped(leaf.cond):
            out[column_key("sp_", leaf.cond.metric)] = alias("sp_", leaf.cond.metric)
        return out

    def _factor_columns(self, factors: list[FactorSpec]) -> dict[str, str]:
        out: dict[str, str] = {}
        for spec in factors:
            out[spec.metric] = self.allow.ident(spec.metric)
            out[column_key("f_", spec.metric)] = self.factor_column(spec)
            if self.screen.rank is not None and self.screen.rank.within is Within.SECTOR:
                out[column_key("sp_", spec.metric)] = alias("sp_", spec.metric)
        return out


def _sector_scoped(cond: Condition) -> bool:
    """Compared through a sector percentile or sector median (null for small sectors)."""
    pct_in_sector = cond.cmp in PCT_RANK_CMPS and cond.within is Within.SECTOR
    return pct_in_sector or cond.cmp in VS_MEDIAN_CMPS


def _projection(columns: dict[str, str]) -> str:
    return ",\n       ".join(
        f"{expr_sql} AS {alias('', name)}" for name, expr_sql in columns.items()
    )


def _layer(source_sql: str, parts_sql: list[str]) -> str:
    """`SELECT *, <parts> FROM <source>`; `source_sql` is one of the CTE names above."""
    if not parts_sql:
        return f"SELECT * FROM {source_sql}"
    joined_sql = ",\n           ".join(parts_sql)
    return f"SELECT *,\n           {joined_sql}\n    FROM {source_sql}"


def compile_screen(
    screen: Screen, registry: MetricRegistry, config: ScreenConfig
) -> CompiledScreen:
    """Compile a validated screen (see `glint.screen.validate.check_screen`)."""
    return _Compiler(screen, registry, config).compile()
