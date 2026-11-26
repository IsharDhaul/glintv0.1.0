# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""/api/snapshot/meta and /api/snapshot/values: the build's numbers, exactly, as columns."""

import gzip
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from fastapi.testclient import TestClient

from glint.contracts.enums import NoteCode
from glint.screen.config import load_screen_config


def _decode(client: TestClient) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    meta = client.get("/api/snapshot/meta").json()
    res = client.get("/api/snapshot/values", headers={"Accept-Encoding": "identity"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert res.headers["x-glint-build"] == meta["build_id"]
    body = res.content
    assert len(body) == meta["values_bytes"] + meta["notes_bytes"]
    m, n = len(meta["metrics"]), meta["n"]
    values = np.frombuffer(body[: meta["values_bytes"]], dtype="<f8").reshape(m, n)
    codes = np.frombuffer(body[meta["values_bytes"] :], dtype=np.uint8).reshape(m, n)
    return meta, values, codes


def test_values_are_the_builds_numbers(client: TestClient, small_data_dir: Path) -> None:
    meta, values, codes = _decode(client)
    pointer = json.loads((small_data_dir / "current.json").read_text())
    with duckdb.connect(str(small_data_dir / pointer["path"]), read_only=True) as con:
        mids = meta["metrics"]
        rows = con.execute(
            f"SELECT cik, {', '.join(mids)} FROM metrics_snapshot ORDER BY cik"
        ).fetchall()
        notes = {
            (c, m): code
            for c, m, code in con.execute(
                "SELECT cik, metric_id, code FROM metric_notes"
            ).fetchall()
        }
    assert [r[0] for r in rows] == meta["rows"]["cik"]
    for i, r in enumerate(rows):
        for j, mid in enumerate(mids):
            v = r[1 + j]
            if v is None:
                assert np.isnan(values[j, i]), (r[0], mid)
            else:
                assert values[j, i] == float(v), (r[0], mid)  # exact: float64, no rounding
            code = notes.get((r[0], mid))
            expected = 0 if code is None else meta["note_codes"].index(code) + 1
            assert codes[j, i] == expected, (r[0], mid)
    # every null carries a reason (principle 3)
    assert not np.any(np.isnan(values) & (codes == 0))


def test_meta_lists_live_metrics_and_every_note_code(client: TestClient) -> None:
    meta = client.get("/api/snapshot/meta").json()
    live = [m["id"] for m in client.get("/api/metrics").json()["metrics"]]
    assert meta["metrics"] == [m for m in live if m in meta["metrics"]]
    assert set(meta["note_codes"]) == {c.value for c in NoteCode}
    assert all(len(v) == meta["n"] for v in meta["rows"].values())
    cfg = load_screen_config()
    assert meta["screen_config"] == {
        "float_tolerance": cfg.float_tolerance,
        "small_peer_group_min": cfg.small_peer_group_min,
    }


def test_gzip_and_cache_headers(client: TestClient) -> None:
    meta = client.get("/api/snapshot/meta").json()
    plain = client.get("/api/snapshot/values", headers={"Accept-Encoding": "identity"})
    assert plain.headers["cache-control"] == "no-cache"
    raw = client.get(
        f"/api/snapshot/values?build={meta['build_id']}",
        headers={"Accept-Encoding": "gzip"},
    )
    assert raw.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "Accept-Encoding" in raw.headers["vary"]
    # TestClient (httpx) decodes gzip transparently: the bytes match the plain body.
    assert raw.content == plain.content or gzip.decompress(raw.content) == plain.content
