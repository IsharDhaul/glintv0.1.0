from pathlib import Path

from glint.core.paths import Paths
from glint.core.settings import REPO_ROOT, Settings
from tests.conftest import make_settings as make


def test_relative_dirs_resolve_against_repo_root() -> None:
    s = make(db_dir=Path("./data"))
    assert s.db_dir == REPO_ROOT / "data"


def test_tilde_expands() -> None:
    s = make(raw_dir=Path("~/GlintData/raw"))
    assert s.raw_dir == Path.home() / "GlintData" / "raw"


def test_blank_optional_keys_are_none() -> None:
    s = make(massive_api_key="", anthropic_api_key="")
    assert s.massive_api_key is None
    assert s.anthropic_api_key is None


def test_placeholder_contact_is_not_configured() -> None:
    assert not make().sec_contact_configured
    assert make(sec_user_agent="Glint me@real.org").sec_contact_configured


def test_env_example_parses(tmp_path: Path) -> None:
    env = (REPO_ROOT / ".env.example").read_text()
    (tmp_path / ".env").write_text(env)
    s = Settings(_env_file=tmp_path / ".env")  # pyright: ignore[reportCallIssue]
    assert s.sec_max_rps == 8
    assert s.massive_calls_per_min == 5
    assert s.massive_api_key is None
    assert s.price_provider == "massive"


def test_paths(settings: Settings) -> None:
    p = Paths.from_settings(settings)
    assert p.raw_lock == settings.raw_dir / "raw.lock"
    assert p.current_pointer == settings.db_dir / "current.json"
    assert p.user_db == settings.db_dir / "user.duckdb"
    assert p.build_db("20261028T000000Z") == settings.db_dir / "builds" / "20261028T000000Z.duckdb"
