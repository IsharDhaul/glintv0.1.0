"""The foreign-checkout guard: glint refuses to run code, `.env` and data from another checkout."""

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from glint.cli import app
from glint.core import settings as settings_mod
from glint.core.settings import (
    ALLOW_FOREIGN_CHECKOUT_ENV,
    ForeignCheckoutError,
    check_checkout,
    checkout_problem,
)


def _main_checkout(root: Path) -> Path:
    """A checkout whose `.git` is a directory."""
    (root / ".git").mkdir(parents=True)
    (root / "engine").mkdir()
    return root


def _worktree(path: Path) -> Path:
    """A git worktree: `.git` is a file pointing at the real gitdir."""
    (path / "engine").mkdir(parents=True)
    (path / ".git").write_text("gitdir: /somewhere/.git/worktrees/x\n")
    return path


@pytest.fixture(autouse=True)
def _fresh_check() -> Iterator[None]:
    check_checkout.cache_clear()
    yield
    check_checkout.cache_clear()


# --- allow -----------------------------------------------------------------------------------


def test_allow_cwd_inside_own_checkout_git_dir(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path / "main")
    assert checkout_problem(main, main, {}) is None
    assert checkout_problem(main, main / "engine", {}) is None


def test_allow_cwd_inside_own_worktree_git_file(tmp_path: Path) -> None:
    wt = _worktree(tmp_path / "wt")
    assert checkout_problem(wt, wt / "engine", {}) is None


def test_allow_own_worktree_nested_under_main(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path / "main")
    wt = _worktree(main / ".claude" / "worktrees" / "fix")
    assert checkout_problem(wt, wt / "engine", {}) is None


def test_allow_outside_any_checkout_when_repo_root_contains_cwd(tmp_path: Path) -> None:
    root = tmp_path / "unpacked"
    (root / "engine").mkdir(parents=True)
    assert checkout_problem(root, root / "engine", {}) is None


# --- refuse ----------------------------------------------------------------------------------


def test_refuse_reported_case_worktree_nested_under_main(tmp_path: Path) -> None:
    """WT-09 bug: VIRTUAL_ENV = main's venv, so REPO_ROOT = main; cwd = a worktree under it."""
    main = _main_checkout(tmp_path / "main")
    wt = _worktree(main / ".claude" / "worktrees" / "fix-core-paths")
    problem = checkout_problem(main, wt / "engine", {})
    assert problem is not None
    assert str(main.resolve()) in problem
    assert str(wt.resolve()) in problem
    assert "unset VIRTUAL_ENV" in problem
    assert "engine/" in problem
    assert ALLOW_FOREIGN_CHECKOUT_ENV in problem


def test_refuse_sibling_checkout_git_dir(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path / "main")
    other = _main_checkout(tmp_path / "other")
    assert checkout_problem(main, other / "engine", {}) is not None


def test_refuse_sibling_worktree_git_file(tmp_path: Path) -> None:
    main = _main_checkout(tmp_path / "main")
    wt = _worktree(tmp_path / "wt")
    assert checkout_problem(main, wt, {}) is not None


def test_refuse_outside_any_checkout(tmp_path: Path) -> None:
    root = tmp_path / "unpacked"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    problem = checkout_problem(root, elsewhere, {})
    assert problem is not None and str(elsewhere.resolve()) in problem


# --- override --------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_override_allows_foreign_checkout(tmp_path: Path, value: str) -> None:
    main = _main_checkout(tmp_path / "main")
    wt = _worktree(main / ".claude" / "worktrees" / "fix")
    assert checkout_problem(main, wt, {ALLOW_FOREIGN_CHECKOUT_ENV: value}) is None


@pytest.mark.parametrize("value", ["", "0", " "])
def test_override_off_values_still_refuse(tmp_path: Path, value: str) -> None:
    main = _main_checkout(tmp_path / "main")
    wt = _worktree(main / ".claude" / "worktrees" / "fix")
    assert checkout_problem(main, wt, {ALLOW_FOREIGN_CHECKOUT_ENV: value}) is not None


# --- wiring: get_settings, the CLI, once per process ------------------------------------------


@pytest.fixture
def foreign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """REPO_ROOT = a main checkout; cwd = a worktree nested under it (the reported case)."""
    main = _main_checkout(tmp_path / "main")
    wt = _worktree(main / ".claude" / "worktrees" / "fix")
    monkeypatch.setattr(settings_mod, "REPO_ROOT", main)
    monkeypatch.chdir(wt / "engine")
    monkeypatch.delenv(ALLOW_FOREIGN_CHECKOUT_ENV, raising=False)
    return wt


def test_get_settings_refuses(foreign: Path) -> None:
    settings_mod.get_settings.cache_clear()
    try:
        with pytest.raises(ForeignCheckoutError):
            settings_mod.get_settings()
    finally:
        settings_mod.get_settings.cache_clear()


def test_cli_refuses_with_message(foreign: Path) -> None:
    # The root callback runs before the subcommand parses its own args, so nothing else runs.
    result = CliRunner().invoke(app, ["universe", "--help"])
    assert result.exit_code == 2
    assert "another checkout" in result.output
    assert ALLOW_FOREIGN_CHECKOUT_ENV in result.output


def test_cli_override_lets_it_through(foreign: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOW_FOREIGN_CHECKOUT_ENV, "1")
    result = CliRunner().invoke(app, ["universe", "--help"])
    assert result.exit_code == 0, result.output


def test_check_runs_once_per_process(foreign: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    real = settings_mod.checkout_problem

    def counting(repo_root: Path, cwd: Path, env: Mapping[str, str]) -> str | None:
        calls.append(cwd)
        return real(repo_root, cwd, {ALLOW_FOREIGN_CHECKOUT_ENV: "1"})

    monkeypatch.setattr(settings_mod, "checkout_problem", counting)
    for _ in range(3):
        check_checkout()
    assert len(calls) == 1
