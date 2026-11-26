"""Kill test (WT-07 acceptance): SIGKILL mid-`metrics` leaves the previous build live."""

import os
import signal
import subprocess
import sys
from pathlib import Path

import duckdb

from glint.core.paths import Paths
from glint.pipeline.swap import pointer_db, read_pointer
from tests.conftest import make_settings

ENGINE = Path(__file__).resolve().parents[2]


def killable(tmp: Path, mode: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "tests.pipeline.killable", str(tmp), mode],
        cwd=ENGINE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ENGINE)},
    )


def test_sigkill_mid_metrics_keeps_the_previous_build(tmp_path: Path) -> None:
    paths = Paths.from_settings(make_settings(raw_dir=tmp_path / "raw", db_dir=tmp_path / "data"))

    good = killable(tmp_path, "good")
    out, _ = good.communicate(timeout=60)
    assert good.returncode == 0, out
    before = read_pointer(paths)
    assert before is not None and before.build_id == "20261030T080000Z"
    pointer_bytes = paths.current_pointer.read_bytes()

    # A reader (as the API would be) holds the live build open read-only throughout.
    with duckdb.connect(str(pointer_db(paths, before)), read_only=True) as api:
        slow = killable(tmp_path, "slow-metrics")
        assert slow.stdout is not None
        line = slow.stdout.readline()
        assert line.strip() == "METRICS_STARTED", line
        slow.send_signal(signal.SIGKILL)
        slow.wait(timeout=10)
        assert slow.returncode == -signal.SIGKILL

        assert paths.current_pointer.read_bytes() == pointer_bytes
        assert api.execute("SELECT ran FROM stage_financials").fetchone() == (1,)

    # A fresh reader still opens the live build; the killed one is left marked "running".
    with duckdb.connect(str(pointer_db(paths, before)), read_only=True) as con:
        assert con.execute("SELECT status FROM pipeline_runs").fetchone() == ("ok",)
    killed = paths.build_db("20261030T090000Z")
    with duckdb.connect(str(killed), read_only=True) as con:
        assert con.execute("SELECT status FROM pipeline_runs").fetchone() == ("running",)
    assert not list(paths.db_dir.glob(".current.json.*.tmp"))
