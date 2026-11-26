"""Shared fixtures. Tests never touch the network or real data directories."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from glint.core.settings import Settings, get_settings


class _IsolatedSettings(Settings):
    """Settings that read only explicit init values: no environment variables, no `.env`."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_settings(**fields: object) -> Settings:
    """Build Settings from explicit fields only: no environment, no `.env`."""
    return _IsolatedSettings.model_validate(fields)


class NetworkBlockedError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Any socket connection outside `@pytest.mark.live` tests fails loudly."""
    if request.node.get_closest_marker("live") is None:

        def guard(*_args: object, **_kwargs: object) -> None:
            raise NetworkBlockedError("network access in a non-live test")

        monkeypatch.setattr(socket.socket, "connect", guard)
        monkeypatch.setattr(socket.socket, "connect_ex", guard)
        monkeypatch.setattr(socket, "create_connection", guard)
        monkeypatch.setattr(socket, "getaddrinfo", guard)
    yield


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings isolated from `.env` and the real data dirs."""
    return make_settings(
        sec_user_agent="Glint tests glint-tests@example.org",
        raw_dir=tmp_path / "raw",
        db_dir=tmp_path / "data",
    )


@pytest.fixture
def db_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point GLINT_DB_DIR (and GLINT_RAW_DIR) at temp dirs for code that reads global settings."""

    data = tmp_path / "data"
    monkeypatch.setenv("GLINT_DB_DIR", str(data))
    monkeypatch.setenv("GLINT_RAW_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    yield data
    get_settings.cache_clear()
