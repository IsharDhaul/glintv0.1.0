"""Small helpers shared by the screen tests."""

import re
from pathlib import Path
from typing import Any

import duckdb

from glint.contracts.metrics import MetricRegistry
from glint.contracts.screen import Screen
from glint.screen.compile import compile_screen
from glint.screen.config import ScreenConfig

_PARAM_RE = re.compile(r"\$(p\d+)\b")


def screen(**fields: Any) -> Screen:
    return Screen.model_validate(fields)


def cond(metric: str, cmp: str, value: Any = None, **kw: Any) -> dict[str, Any]:
    return {"metric": metric, "cmp": cmp, "value": value, **kw}


def and_(*children: dict[str, Any]) -> dict[str, Any]:
    return {"op": "and", "children": list(children)}


def or_(*children: dict[str, Any]) -> dict[str, Any]:
    return {"op": "or", "children": list(children)}


def compiled_rows(
    db: Path, s: Screen, registry: MetricRegistry, config: ScreenConfig
) -> list[dict[str, Any]]:
    """Run the compiled screen query and return its rows as dicts."""
    c = compile_screen(s, registry, config)
    used = set(_PARAM_RE.findall(c.sql))
    with duckdb.connect(str(db), read_only=True) as con:
        rows = con.execute(c.sql, {k: v for k, v in c.params.items() if k in used}).fetchall()
    return [dict(zip(c.row_columns, r, strict=True)) for r in rows]


def snapshot(db: Path, *columns: str) -> list[dict[str, Any]]:
    """Whole snapshot, selected columns (test-only SQL over fixed, literal column names)."""
    cols = ", ".join(columns)
    with duckdb.connect(str(db), read_only=True) as con:
        rows = con.execute(f"SELECT {cols} FROM metrics_snapshot ORDER BY ticker").fetchall()
    return [dict(zip(columns, r, strict=True)) for r in rows]
