"""Smoke runs through the API, so it reuses the API tests' synthetic builds and clients."""

# pyright: reportUnusedImport=false

from tests.api.conftest import (  # noqa: F401 (pytest finds fixtures by name)
    client,
    client_for,
    live_registry,
    small_data_dir,
)
