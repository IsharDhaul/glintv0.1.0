"""Run report (SPEC §4.6, WT-07 step 6): `data/reports/<build_id>.md` plus a console summary.

Compared with the previous build (the one `current.json` pointed at when the run started, if it
was a real build):

- **Coverage per core line item**: the share of default-universe companies with a current value
  (TTM for flows, MRQ for instants: WT-03's coverage definition), per group. The financials
  stage stores the integer counts in `pipeline_runs.counts`, so any build can be compared with
  the next one.
- **Null rate per P0 metric**: the share of default-universe `metrics_snapshot` rows where the
  metric is null (once WT-06's metrics stage exists).

A coverage drop, or a null-rate rise, of more than `audit.coverage_drop_warn_pp`
(config/thresholds.yaml) is a warning. Warnings are questions for a human; nothing is fixed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import duckdb
import orjson
import yaml

from glint.contracts.db import CurrentPointer
from glint.contracts.enums import DEFAULT_EXCHANGES, Kind, Priority
from glint.contracts.metrics import load_registry
from glint.core.errors import ContractError
from glint.core.paths import Paths
from glint.core.settings import REPO_ROOT
from glint.financials.coverage import Group

if TYPE_CHECKING:
    from glint.pipeline.runner import RunReport

THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
GROUPS = [g.name.lower() for g in Group]
GROUP_LABEL = {g.name.lower(): g.value for g in Group}


def coverage_drop_threshold(path: Path = THRESHOLDS_PATH) -> float:
    doc = yaml.safe_load(path.read_text())
    try:
        return float(doc["audit"]["coverage_drop_warn_pp"])
    except (KeyError, TypeError) as exc:
        raise ContractError(f"{path}: audit.coverage_drop_warn_pp is missing") from exc


Shares = dict[str, dict[str, float | None]]  # group -> item -> share


def coverage_from_counts(counts: dict[str, int]) -> Shares:
    """`coverage.<group>.<item>` counts (financials stage) → shares per group and item."""
    out: Shares = {}
    for group in GROUPS:
        n = counts.get(f"coverage.{group}.companies", 0)
        prefix = f"coverage.{group}."
        items = {
            k[len(prefix) :]: v
            for k, v in counts.items()
            if k.startswith(prefix) and k != f"{prefix}companies"
        }
        out[group] = {item: (v / n if n else None) for item, v in sorted(items.items())}
    return out


def previous_counts(db: Path) -> dict[str, dict[str, int]] | None:
    """Per-stage counts of the last successful run recorded in a build, if any."""
    if not db.exists():
        return None
    try:
        with duckdb.connect(str(db), read_only=True) as con:
            row = con.execute(
                "SELECT counts FROM pipeline_runs WHERE status IN ('ok', 'warn') "
                "ORDER BY finished DESC LIMIT 1"
            ).fetchone()
    except duckdb.Error:
        return None
    return orjson.loads(row[0]) if row else None


def null_rates(db: Path) -> dict[str, float | None] | None:
    """Null share per live P0 metric over the default universe; None without metrics yet."""
    if not db.exists():
        return None
    registry = load_registry()
    exchanges = ", ".join(f"'{e.value}'" for e in DEFAULT_EXCHANGES)
    try:
        with duckdb.connect(str(db), read_only=True) as con:
            cols = {r[0] for r in con.execute("DESCRIBE metrics_snapshot").fetchall()}
            ids = [m.id for m in registry if m.priority is Priority.P0 and m.id in cols]
            if not ids:
                return None
            where = f"kind = '{Kind.OPERATING.value}' AND exchange IN ({exchanges}) AND has_facts"
            sums = ", ".join(f"avg(CASE WHEN {i} IS NULL THEN 1 ELSE 0 END)" for i in ids)
            row = con.execute(f"SELECT {sums} FROM metrics_snapshot WHERE {where}").fetchone()
    except duckdb.Error:
        return None
    if row is None:
        return None
    return {i: (None if v is None else float(v)) for i, v in zip(ids, row, strict=True)}


@dataclass
class Comparison:
    previous_build: str | None
    threshold: float
    coverage: Shares = field(default_factory=dict[str, dict[str, float | None]])
    coverage_prev: Shares | None = None
    nulls: dict[str, float | None] | None = None
    nulls_prev: dict[str, float | None] | None = None
    universe: dict[str, int] = field(default_factory=dict[str, int])
    universe_prev: dict[str, int] | None = None
    warnings: list[str] = field(default_factory=list[str])


def _pp(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def compare(
    paths: Paths,
    build_db: Path,
    counts: dict[str, dict[str, int]],
    previous: CurrentPointer | None,
) -> Comparison:
    """This run's coverage and null rates against the previous real build's."""
    real_prev = previous if previous is not None and not previous.synthetic else None
    prev_db = paths.db_dir / real_prev.path if real_prev else None
    prev_counts = previous_counts(prev_db) if prev_db else None
    cmp = Comparison(
        previous_build=real_prev.build_id if real_prev else None,
        threshold=coverage_drop_threshold(),
        coverage=coverage_from_counts(counts.get("financials", {})),
        nulls=null_rates(build_db),
        universe=counts.get("companies", {}),
    )
    if prev_counts is not None:
        cmp.coverage_prev = coverage_from_counts(prev_counts.get("financials", {}))
        cmp.universe_prev = prev_counts.get("companies")
    if prev_db is not None:
        cmp.nulls_prev = null_rates(prev_db)

    t = cmp.threshold
    for group, items in cmp.coverage.items():
        before = (cmp.coverage_prev or {}).get(group, {})
        for item, now in items.items():
            d = _pp(now, before.get(item))
            if d is not None and d < -t:
                cmp.warnings.append(
                    f"coverage of {item} ({GROUP_LABEL[group]}) fell {-d * 100:.1f} pp: "
                    f"{_pct(before.get(item))} → {_pct(now)}. What changed in the source?"
                )
    nulls_prev = cmp.nulls_prev or {}
    for metric, now in (cmp.nulls or {}).items():
        d = _pp(now, nulls_prev.get(metric))
        if d is not None and d > t:
            cmp.warnings.append(
                f"null rate of {metric} rose {d * 100:.1f} pp: "
                f"{_pct(nulls_prev.get(metric))} → {_pct(now)}. Which input went missing?"
            )
    return cmp


# --- rendering ---------------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _delta(now: float | None, prev: float | None, threshold: float, *, rise_is_bad: bool) -> str:
    d = _pp(now, prev)
    if d is None:
        return "—"
    bad = d > threshold if rise_is_bad else d < -threshold
    text = f"{d * 100:+.1f}"
    return f"**{text} ⚠**" if bad else text


def _times(dt: datetime) -> str:
    return (
        f"{dt:%Y-%m-%d %H:%M:%S} UTC · {dt.astimezone(LONDON):%H:%M %Z} London · "
        f"{dt.astimezone(NEW_YORK):%H:%M %Z} New York"
    )


def run_warnings(report: "RunReport") -> list[str]:
    """Every warning of a run, prefixed by where it came from (also `pipeline_runs.warnings`)."""
    out = [f"{s.name}: {w}" for s in report.stages if s.result for w in s.result.warnings]
    cmp = report.comparison
    out += [f"report: {w}" for w in (cmp.warnings if cmp else [])]
    return out + [f"publish: {n}" for n in report.notices]


def render(report: "RunReport", cmp: Comparison | None) -> str:
    """Markdown for one run."""
    lines = [
        f"# Glint build {report.build_id}",
        "",
        f"- **Status:** {report.status}"
        + (f" (failed in `{report.failed_stage}`: {report.error})" if report.error else ""),
        f"- **Started:** {_times(report.started)}",
        f"- **Duration:** {report.seconds:,.1f} s",
        f"- **Published:** {'yes, current.json points here' if report.published else 'no'}",
        f"- **Previous build:** {report.previous.build_id if report.previous else 'none'}"
        + (" (synthetic, not compared)" if report.previous and report.previous.synthetic else ""),
    ]
    if report.partial:
        lines.append("- **Partial run:** started from a copy of the previous build")
    if report.log_path:
        lines.append(f"- **Log:** `{report.log_path}`")

    lines += [
        "",
        "## Stages",
        "",
        "| stage | status | seconds | counts | note |",
        "|---|---|--:|---|---|",
    ]
    for s in report.stages:
        r = s.result
        counts = ""
        if r is not None:
            counts = ", ".join(f"{k} {v:,}" for k, v in r.counts.items() if "." not in k)
        secs = f"{r.duration_s:,.1f}" if r is not None else ""
        note = s.skip_reason or s.note or (r.error if r is not None and r.error else "") or ""
        lines.append(f"| {s.name} | {s.status} | {secs} | {counts} | {note} |")

    if cmp is not None:
        lines += _universe_section(cmp) + _coverage_section(cmp) + _nulls_section(cmp)

    lines += ["", "## Warnings", ""]
    lines += [f"- {w}" for w in run_warnings(report)] or ["None."]
    lines += ["", "_Educational tool. Not investment advice._", ""]
    return "\n".join(lines)


def _universe_section(cmp: Comparison) -> list[str]:
    if not cmp.universe:
        return []
    prev = cmp.universe_prev or {}
    out = ["", "## Universe", "", "| | this build | previous |", "|---|--:|--:|"]
    for k, v in cmp.universe.items():
        p = prev.get(k)
        out.append(f"| {k.replace('_', ' ')} | {v:,} | {'—' if p is None else f'{p:,}'} |")
    return out


def _coverage_section(cmp: Comparison) -> list[str]:
    if not any(cmp.coverage.values()):
        return ["", "## Coverage", "", "Not recomputed in this run (financials didn't run)."]
    t = cmp.threshold
    head = "| line item | " + " | ".join(f"{GROUP_LABEL[g]} | prev | Δ pp" for g in GROUPS)
    out = [
        "",
        "## Coverage per core line item",
        "",
        "Share of default-universe companies with a current value (TTM flows, MRQ instants). "
        f"Δ in percentage points; a drop of more than {t * 100:g} pp is flagged ⚠.",
        "",
        head + " |",
        "|---|" + "--:|--:|--:|" * len(GROUPS),
    ]
    items = sorted({i for g in cmp.coverage.values() for i in g})
    prev = cmp.coverage_prev or {}
    for item in items:
        cells: list[str] = []
        for g in GROUPS:
            now, before = cmp.coverage.get(g, {}).get(item), prev.get(g, {}).get(item)
            cells += [_pct(now), _pct(before), _delta(now, before, t, rise_is_bad=False)]
        out.append(f"| {item} | " + " | ".join(cells) + " |")
    if cmp.coverage_prev is None:
        out += ["", "No previous real build to compare with."]
    return out


def _nulls_section(cmp: Comparison) -> list[str]:
    out = ["", "## Null rate per P0 metric", ""]
    if cmp.nulls is None:
        return [*out, "No metrics in this build yet (the metrics stage is WT-06)."]
    out += [
        "Share of default-universe rows where the metric is null (each null has a reason code "
        "in `metric_notes`).",
        "",
        "| metric | this build | previous | Δ pp |",
        "|---|--:|--:|--:|",
    ]
    prev = cmp.nulls_prev or {}
    for m, now in cmp.nulls.items():
        out.append(
            f"| {m} | {_pct(now)} | {_pct(prev.get(m))} | "
            f"{_delta(now, prev.get(m), cmp.threshold, rise_is_bad=True)} |"
        )
    return out


def write_report(paths: Paths, build_id: str, markdown: str) -> Path:
    path = paths.db_dir / "reports" / f"{build_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(markdown)
    tmp.replace(path)
    return path
