from pathlib import Path

import pytest
from pydantic import ValidationError

from glint.core.errors import ContractError
from glint.universe.predecessors import load_predecessors

ENTRY = """
  - successor_cik: "{s}"
    predecessor_cik: "{p}"
    name: "x"
    reason: "x"
    evidence: "x"
    added: 2026-10-29
"""


def write(tmp_path: Path, *pairs: tuple[str, str]) -> Path:
    body = "links:" + "".join(ENTRY.format(s=s, p=p) for s, p in pairs)
    path = tmp_path / "cik_predecessors.yaml"
    path.write_text(body)
    return path


def test_committed_config_links_xom() -> None:
    links = load_predecessors()
    xom = links["0002115436"]
    assert xom.predecessor_cik == "0000034088"
    assert "25-NSE" in xom.evidence


def test_rejects_bad_ciks_and_self_links(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_predecessors(write(tmp_path, ("2115436", "0000034088")))
    with pytest.raises(ValidationError):
        load_predecessors(write(tmp_path, ("0000000001", "0000000001")))


def test_rejects_duplicates_and_chains(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="listed twice"):
        load_predecessors(
            write(tmp_path, ("0000000001", "0000000002"), ("0000000001", "0000000003"))
        )
    with pytest.raises(ContractError, match="claimed twice"):
        load_predecessors(
            write(tmp_path, ("0000000001", "0000000002"), ("0000000003", "0000000002"))
        )
    with pytest.raises(ContractError, match="chained"):
        load_predecessors(
            write(tmp_path, ("0000000001", "0000000002"), ("0000000002", "0000000003"))
        )


def test_empty_file_is_no_links(tmp_path: Path) -> None:
    path = tmp_path / "cik_predecessors.yaml"
    path.write_text("links: []\n")
    assert load_predecessors(path) == {}
