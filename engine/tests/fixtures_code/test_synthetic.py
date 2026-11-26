# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from pathlib import Path

import duckdb
import orjson
import pytest
from fastapi.testclient import TestClient

from glint.api.app import create_app
from glint.contracts.db import DB_SCHEMA_VERSION
from glint.contracts.enums import NON_NULL_NOTE_CODES, NoteCode
from glint.contracts.metrics import load_registry
from glint.core.paths import Paths
from glint.fixtures import synthetic

N = 300


@pytest.fixture
def built(db_dir: Path, tmp_path: Path) -> tuple[Path, Path, synthetic.SyntheticBuild]:
    mocks = tmp_path / "mocks"
    db_path, build = synthetic.run(N, 7, Paths.from_settings(), mocks)
    return db_path, mocks, build


def test_rows_are_unmistakably_synthetic(
    built: tuple[Path, Path, synthetic.SyntheticBuild],
) -> None:
    db_path, _, _ = built
    with duckdb.connect(str(db_path), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM metrics_snapshot").fetchone() == (N,)
        assert con.execute("SELECT DISTINCT kind FROM companies").fetchall() == [("synthetic",)]
        assert con.execute("SELECT DISTINCT kind FROM metrics_snapshot").fetchall() == [
            ("synthetic",)
        ]
        names = con.execute(
            "SELECT min(primary_ticker), max(name), min(cik) FROM companies"
        ).fetchone()
        assert names == ("SYN0001", f"Synthetic Co {N:04d}", "9000000001")
        meta = dict(con.execute("SELECT key, value FROM build_meta").fetchall())
        assert meta["synthetic"] == "true"
        assert meta["db_schema_version"] == str(DB_SCHEMA_VERSION)


def test_every_null_has_a_valid_reason(built: tuple[Path, Path, synthetic.SyntheticBuild]) -> None:
    _, _, build = built
    nulls = 0
    cells = 0
    for values, notes in zip(build.values, build.notes, strict=True):
        for mid, v in values.items():
            cells += 1
            if v is None:
                nulls += 1
                assert mid in notes
                assert notes[mid][0] not in NON_NULL_NOTE_CODES
            elif mid in notes:
                assert notes[mid][0] in NON_NULL_NOTE_CODES
    assert 0.05 < nulls / cells < 0.2


def test_nm_follows_applicability(built: tuple[Path, Path, synthetic.SyntheticBuild]) -> None:
    db_path, _, _ = built
    with duckdb.connect(str(db_path), read_only=True) as con:
        bank_gm = con.execute(
            "SELECT DISTINCT n.code FROM metric_notes n JOIN companies c USING (cik) "
            "WHERE c.sector = 'Banks' AND n.metric_id = 'gross_margin'"
        ).fetchall()
    assert bank_gm in ([], [(NoteCode.NOT_APPLICABLE_SECTOR.value,)])


def test_same_seed_same_build(db_dir: Path) -> None:
    reg = load_registry(treat_all_as_live=True)
    a = synthetic.generate(50, 7, reg)
    b = synthetic.generate(50, 7, reg)
    assert a.values == b.values and a.notes == b.notes


def test_api_meta_reports_synthetic(built: tuple[Path, Path, synthetic.SyntheticBuild]) -> None:
    r = TestClient(create_app()).get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["synthetic"] is True
    assert body["build_id"] == "synthetic"
    assert body["universe_counts"]["companies"] == N


def test_mocks_exported(built: tuple[Path, Path, synthetic.SyntheticBuild]) -> None:
    _, mocks, _ = built
    meta = orjson.loads((mocks / "meta.json").read_bytes())
    assert meta["synthetic"] is True
    metrics = orjson.loads((mocks / "metrics.json").read_bytes())
    assert len(metrics["metrics"]) == 71
    companies = orjson.loads((mocks / "companies.json").read_bytes())
    assert companies["synthetic"] is True
    assert companies["rows"][0]["ticker"] == "SYN0001"


def test_reason_codes_match_the_formula_rules(
    built: tuple[Path, Path, synthetic.SyntheticBuild],
) -> None:
    _, _, build = built
    codes = {(mid, code) for notes in build.notes for mid, (code, _) in notes.items()}
    assert ("interest_coverage", NoteCode.NO_INTEREST_EXPENSE) in codes
    assert ("interest_coverage", NoteCode.NEGATIVE_DENOMINATOR) not in codes
    assert ("roic", NoteCode.ASSUMED_TAX_RATE) in codes


def test_every_null_cell_in_the_db_has_a_note(
    built: tuple[Path, Path, synthetic.SyntheticBuild],
) -> None:
    db_path, _, _ = built
    reg = load_registry(treat_all_as_live=True)
    with duckdb.connect(str(db_path), read_only=True) as con:
        for m in reg:
            orphans = con.execute(
                f"SELECT count(*) FROM metrics_snapshot s LEFT JOIN metric_notes n "
                f"ON n.cik = s.cik AND n.metric_id = '{m.id}' "
                f"WHERE s.{m.id} IS NULL AND n.code IS NULL"
            ).fetchone()
            assert orphans == (0,), m.id


def test_meta_trusts_the_build_over_the_pointer(
    built: tuple[Path, Path, synthetic.SyntheticBuild], db_dir: Path
) -> None:
    pointer = db_dir / "current.json"
    pointer.write_text(pointer.read_text().replace('"synthetic": true', '"synthetic": false'))
    body = TestClient(create_app()).get("/api/meta").json()
    assert body["synthetic"] is True
    assert body["warnings"] == ["Synthetic data: not real companies or numbers."]
