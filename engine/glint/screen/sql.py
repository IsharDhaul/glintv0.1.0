"""The only two ways anything reaches the screen SQL: bound parameters and allow-listed names.

User values never enter the SQL text. They're bound as named parameters (`$p0`, `$p1`, …).
Column names come only from the snapshot's fixed columns plus registry metric ids, and must
also match the snake_case pattern before they're quoted.
"""

import re
from collections.abc import Iterable
from typing import Any

from glint.contracts.db import SNAPSHOT_FIXED_COLUMNS
from glint.contracts.metrics import MetricRegistry
from glint.core.errors import ContractError

SNAPSHOT_TABLE = "metrics_snapshot"
_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Params:
    """Collects bound values; `bind` returns the placeholder to put in the SQL."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def bind(self, value: Any) -> str:
        name = f"p{len(self.values)}"
        self.values[name] = value
        return f"${name}"


class AllowList:
    """Snapshot column names a screen may reference."""

    def __init__(self, names: Iterable[str]) -> None:
        self._names = frozenset(names)

    @classmethod
    def for_registry(cls, registry: MetricRegistry) -> "AllowList":
        return cls([name for name, _ in SNAPSHOT_FIXED_COLUMNS] + [m.id for m in registry])

    def __contains__(self, name: object) -> bool:
        return name in self._names

    def ident(self, name: str) -> str:
        """A quoted snapshot column; raises unless the name is allow-listed and snake_case."""
        if name not in self._names or not _IDENT_RE.match(name):
            raise ContractError(f"{name!r} is not a known snapshot column")
        return f'"{name}"'


def column_key(prefix: str, name: str | int) -> str:
    """A derived column name (`pr_s_roic`, `l3_ok`), unquoted; must be snake_case."""
    full = f"{prefix}{name}"
    if not _IDENT_RE.match(full):
        raise ContractError(f"bad alias {full!r}")
    return full


def alias(prefix: str, name: str | int) -> str:
    """`column_key`, quoted for SQL."""
    return f'"{column_key(prefix, name)}"'
