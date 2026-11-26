"""Why a company passed (or didn't): every filter leaf of a screen, evaluated for one company.

The screen is decoded from `?screen=` (lz-string, §2.12) and run through WT-04's compiler
unchanged, plus one `pct_rank` leaf per numeric metric (sector scope) appended to read the
company's sector percentile. Each original leaf keeps its index, so its `l<i>_ok` column is
the engine's own verdict, not a re-implementation. Percentiles are ascending (0 = lowest in
the sector, 1 = highest), over the screen's universe, as in `pct_rank_*` filters.
"""

import json
from typing import Any

from pydantic import ValidationError

from glint.api.build import Build
from glint.api.errors import ApiError, validation_path
from glint.api.lzstring import LzStringError, decompress_from_encoded_uri_component
from glint.api.routers.screen import used_params
from glint.contracts.api import CellValue, ErrorCode, FilterOutcome
from glint.contracts.enums import Unit
from glint.contracts.screen import (
    CATEGORICAL_FIELDS,
    Comparator,
    Condition,
    Group,
    LogicOp,
    Screen,
    Within,
)
from glint.screen.compile import compile_screen
from glint.screen.config import load_screen_config
from glint.screen.labels import condition_label
from glint.screen.validate import InvalidScreenError, check_screen

UNIVERSE_PATH: list[str | int] = ["universe"]
_CIK_PARAM = "why_cik"


def decode_screen(encoded: str) -> Screen:
    """`?screen=` → Screen; 422 INVALID_SCREEN with a path under `screen` if it isn't one."""
    try:
        text = decompress_from_encoded_uri_component(encoded)
        raw: Any = json.loads(text)
    except (LzStringError, ValueError) as exc:
        raise ApiError(
            422,
            ErrorCode.INVALID_SCREEN,
            f"screen is not lz-string compressed Screen JSON: {exc}",
            ["screen"],
        ) from exc
    try:
        return Screen.model_validate(raw)
    except ValidationError as exc:
        errors: list[dict[str, Any]] = list(exc.errors())  # pyright: ignore[reportAssignmentType]
        message = str(errors[0].get("msg", "invalid screen")) if errors else "invalid screen"
        raise ApiError(
            422, ErrorCode.INVALID_SCREEN, message, ["screen", *validation_path(errors)]
        ) from exc


def _leaves(group: Group) -> list[Condition]:
    """Depth-first, the order the compiler numbers leaves in."""
    out: list[Condition] = []
    for child in group.children:
        out.extend(_leaves(child) if isinstance(child, Group) else [child])
    return out


def _leaf_paths(group: Group, path: list[str | int]) -> list[list[str | int]]:
    out: list[list[str | int]] = []
    for i, child in enumerate(group.children):
        child_path = [*path, "children", i]
        out.extend(_leaf_paths(child, child_path) if isinstance(child, Group) else [child_path])
    return out


def why_passed(build: Build, screen: Screen, cik: str) -> list[FilterOutcome]:
    registry = build.registry
    try:
        check_screen(screen, registry)
    except InvalidScreenError as exc:
        path = list(exc.issues[0].path) if exc.issues else []
        raise ApiError(422, ErrorCode.INVALID_SCREEN, exc.message, ["screen", *path]) from exc

    leaves = _leaves(screen.filters)
    paths = _leaf_paths(screen.filters, ["filters"])
    numeric = list(
        dict.fromkeys(
            c.metric
            for c in leaves
            if c.metric not in CATEGORICAL_FIELDS
            and (m := registry.get(c.metric)) is not None
            and m.unit is not Unit.BOOL
        )
    )
    probes = [
        Condition(metric=m, cmp=Comparator.PCT_RANK_GTE, value=0, within=Within.SECTOR)
        for m in numeric
    ]
    derived = Screen(
        universe=screen.universe,
        filters=Group(op=LogicOp.AND, children=[*screen.filters.children, *probes]),
        columns=["ticker"],
        near_misses=False,
    )
    compiled = compile_screen(derived, registry, load_screen_config())
    sql = f"SELECT * FROM ({compiled.sql}) AS why WHERE why.cik = ${_CIK_PARAM}"
    params = used_params(compiled.sql, compiled.params) | {_CIK_PARAM: cik}
    row = build.cursor().execute(sql, params).fetchone()

    outcomes = [
        FilterOutcome(
            filter_path=UNIVERSE_PATH,
            label="Universe",
            passed=row is not None,
            value=None,
            sector_percentile=None,
        )
    ]
    if row is None:
        # Outside the screen's universe, its filters (and percentiles) aren't evaluated.
        return outcomes
    values: dict[str, Any] = dict(zip(compiled.row_columns, row, strict=True))
    percentile = {m: values[f"l{len(leaves) + j}_v"] for j, m in enumerate(numeric)}
    for i, (cond, path) in enumerate(zip(leaves, paths, strict=True)):
        raw = values[cond.metric]
        value: CellValue = raw if raw is None or isinstance(raw, bool | str) else float(raw)
        pct = percentile.get(cond.metric)
        outcomes.append(
            FilterOutcome(
                filter_path=path,
                label=condition_label(cond, registry),
                passed=bool(values[f"l{i}_ok"]),
                value=value,
                sector_percentile=None if pct is None else float(pct),
            )
        )
    return outcomes
