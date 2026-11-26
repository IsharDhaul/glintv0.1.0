"""`glint serve` hands the app factory to uvicorn on GLINT_API_PORT."""

from pathlib import Path
from typing import Any

import pytest
import uvicorn
from typer.testing import CliRunner

import glint.api.cli
from glint.cli import app


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake_run(target: str, **kwargs: Any) -> None:
        seen.append({"target": target, **kwargs})

    monkeypatch.setattr(uvicorn, "run", fake_run)
    # Logging setup would bind a handler to CliRunner's stderr, which closes after the call.
    monkeypatch.setattr(glint.api.cli, "configure_logging", lambda: None)
    return seen


def test_serve_uses_glint_api_port(
    calls: list[dict[str, Any]], db_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLINT_API_PORT", "8008")
    from glint.core.settings import get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "target": "glint.api.app:create_app",
            "factory": True,
            "host": "127.0.0.1",
            "port": 8008,
            "reload": True,
            "log_config": None,
            "access_log": False,
        }
    ]


def test_serve_flags(calls: list[dict[str, Any]], db_dir: Path) -> None:
    result = CliRunner().invoke(app, ["serve", "--port", "8123", "--no-reload"])
    assert result.exit_code == 0, result.output
    assert (calls[0]["port"], calls[0]["reload"]) == (8123, False)
