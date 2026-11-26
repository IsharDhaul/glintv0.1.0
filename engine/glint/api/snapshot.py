"""The build's metric values as columns (`/api/snapshot/*`), for live screening in the browser.

The browser compares these numbers with the user's thresholds while they drag; it never computes
a metric. Every settled screen still runs on the server, which is authoritative. Layout:
`SnapshotMeta` (glint/contracts/api.py)."""

import gzip
from dataclasses import dataclass

import numpy as np

from glint.api.build import Build
from glint.contracts.api import SnapshotMeta, SnapshotRows, SnapshotScreenConfig
from glint.contracts.enums import Exchange, Kind, NoteCode, Sector, Unit
from glint.contracts.metrics import MetricRegistry
from glint.screen.config import load_screen_config

NOTE_CODES: list[NoteCode] = list(NoteCode)
_CODE_INDEX = {code.value: k + 1 for k, code in enumerate(NOTE_CODES)}


@dataclass(frozen=True)
class Snapshot:
    meta: SnapshotMeta
    body: bytes
    body_gzip: bytes


def snapshot_metrics(registry: MetricRegistry, columns: set[str]) -> list[str]:
    """Live metrics present in `metrics_snapshot`, in registry order."""
    return [m.id for m in registry.live() if m.id in columns]


def encode(values: np.ndarray, codes: np.ndarray) -> bytes:
    """`values`: (metrics, n) float64 with NaN for null; `codes`: (metrics, n) uint8."""
    return values.astype("<f8", copy=False).tobytes() + codes.astype(np.uint8, copy=False).tobytes()


def build_snapshot(build: Build, registry: MetricRegistry) -> Snapshot:
    cur = build.cursor()
    columns = {r[0] for r in cur.execute("DESCRIBE metrics_snapshot").fetchall()}
    metric_ids = snapshot_metrics(registry, columns)
    units = {m.id: m.unit for m in registry}

    fixed = [
        "cik",
        "ticker",
        "name",
        "sector",
        "exchange",
        "kind",
        "is_foreign_filer",
        "is_stale",
        "has_facts",
    ]
    rows = cur.execute(
        f"SELECT {', '.join(fixed + metric_ids)} FROM metrics_snapshot ORDER BY cik"
    ).fetchall()
    n = len(rows)
    index = {r[0]: i for i, r in enumerate(rows)}

    values = np.full((len(metric_ids), n), np.nan, dtype=np.float64)
    for i, r in enumerate(rows):
        for j, mid in enumerate(metric_ids):
            v = r[len(fixed) + j]
            if v is None:
                continue
            values[j, i] = (1.0 if v else 0.0) if units[mid] is Unit.BOOL else float(v)

    codes = np.zeros((len(metric_ids), n), dtype=np.uint8)
    metric_pos = {mid: j for j, mid in enumerate(metric_ids)}
    for cik, mid, code in cur.execute("SELECT cik, metric_id, code FROM metric_notes").fetchall():
        i, j = index.get(cik), metric_pos.get(mid)
        if i is not None and j is not None:
            codes[j, i] = _CODE_INDEX[code]

    meta = SnapshotMeta(
        build_id=build.build_id,
        n=n,
        metrics=metric_ids,
        note_codes=NOTE_CODES,
        rows=SnapshotRows(
            cik=[r[0] for r in rows],
            ticker=[r[1] for r in rows],
            name=[r[2] for r in rows],
            sector=[Sector(r[3]) for r in rows],
            exchange=[Exchange(r[4]) if r[4] is not None else None for r in rows],
            kind=[Kind(r[5]) for r in rows],
            is_foreign_filer=[bool(r[6]) for r in rows],
            is_stale=[bool(r[7]) for r in rows],
            has_facts=[bool(r[8]) for r in rows],
        ),
        screen_config=SnapshotScreenConfig(
            float_tolerance=load_screen_config().float_tolerance,
            small_peer_group_min=load_screen_config().small_peer_group_min,
        ),
        values_bytes=n * len(metric_ids) * 8,
        notes_bytes=n * len(metric_ids),
    )
    body = encode(values, codes)
    return Snapshot(meta=meta, body=body, body_gzip=gzip.compress(body, compresslevel=6))


def snapshot_for(build: Build) -> Snapshot:
    """Built once per build, then served from memory. The registry is read first: `Build.cached`
    holds a non-reentrant lock while it builds, so the builder must not call `cached` again."""
    registry = build.registry
    return build.cached("snapshot", lambda b: build_snapshot(b, registry))
