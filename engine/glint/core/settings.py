"""Settings from the environment and the repo-root `.env`.

Relative paths resolve against the repo root (not the cwd), so `GLINT_DB_DIR=./data` means the
same folder whether a command runs from the root or from `engine/`.

`REPO_ROOT` is where the *imported package* lives. When `VIRTUAL_ENV` points at another
checkout's venv, that is the other checkout, so `check_checkout()` refuses to run unless the
checkout you are standing in is `REPO_ROOT` (override: `GLINT_ALLOW_FOREIGN_CHECKOUT=1`).
"""

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
PLACEHOLDER_CONTACT = "you@example.com"
ALLOW_FOREIGN_CHECKOUT_ENV = "GLINT_ALLOW_FOREIGN_CHECKOUT"


class ForeignCheckoutError(RuntimeError):
    """The imported glint package belongs to a different checkout than the cwd."""


def _checkout_root(cwd: Path) -> Path | None:
    """Nearest folder at or above `cwd` with a `.git` directory, or a `.git` file (a worktree)."""
    for folder in (cwd, *cwd.parents):
        if (folder / ".git").exists():
            return folder
    return None


def checkout_problem(repo_root: Path, cwd: Path, env: Mapping[str, str]) -> str | None:
    """Why running in `cwd` would use another checkout's code, `.env` and data; None if fine.

    The nearest checkout root must be `repo_root` itself: worktrees live inside the main checkout
    (`.claude/worktrees/<name>`), so "repo_root is an ancestor of cwd" alone would pass the bug.
    Outside any git checkout, falls back to that ancestor test.
    """
    if env.get(ALLOW_FOREIGN_CHECKOUT_ENV, "").strip() not in ("", "0"):
        return None
    repo_root, cwd = repo_root.resolve(), cwd.resolve()
    here = _checkout_root(cwd)
    if here is None:
        if cwd == repo_root or repo_root in cwd.parents:
            return None
        here = cwd
    elif here == repo_root:
        return None
    return (
        "glint is running from another checkout.\n"
        f"  code, .env and ./data would come from: {repo_root}\n"
        f"  but you are in:                        {here}\n"
        "Usually VIRTUAL_ENV points at the other checkout's venv. Fix: `unset VIRTUAL_ENV` and "
        "run from this checkout's engine/, so `uv run` uses its own .venv. "
        f"If this is intended, set {ALLOW_FOREIGN_CHECKOUT_ENV}=1."
    )


@lru_cache(maxsize=1)
def check_checkout() -> None:
    """Refuse to run against another checkout. Checked once per process."""
    problem = checkout_problem(REPO_ROOT, Path.cwd(), os.environ)
    if problem:
        raise ForeignCheckoutError(problem)


def _resolve(value: Path) -> Path:
    path = value.expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    sec_user_agent: str = Field(
        default=f"Glint research tool {PLACEHOLDER_CONTACT}", alias="GLINT_SEC_USER_AGENT"
    )
    sec_max_rps: float = Field(default=8, gt=0, le=10, alias="GLINT_SEC_MAX_RPS")

    raw_dir: Path = Field(default=Path("~/GlintData/raw"), alias="GLINT_RAW_DIR")
    db_dir: Path = Field(default=Path("./data"), alias="GLINT_DB_DIR")

    price_provider: Literal["massive", "yfinance"] = Field(
        default="massive", alias="GLINT_PRICE_PROVIDER"
    )
    massive_api_key: str | None = Field(default=None, alias="MASSIVE_API_KEY")
    massive_calls_per_min: int = Field(default=5, gt=0, alias="MASSIVE_CALLS_PER_MIN")

    api_port: int = Field(default=8000, alias="GLINT_API_PORT")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    llm_model: str | None = Field(default=None, alias="GLINT_LLM_MODEL")
    taproot_url: str | None = Field(
        default=None, validation_alias=AliasChoices("TAPROOT_URL", "taproot_url")
    )

    @field_validator("raw_dir", "db_dir", mode="after")
    @classmethod
    def _resolve_dir(cls, value: Path) -> Path:
        return _resolve(value)

    @field_validator("massive_api_key", "anthropic_api_key", "llm_model", "taproot_url")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None

    @property
    def sec_contact_configured(self) -> bool:
        """SEC fair access needs a real contact address in the User-Agent."""
        return "@" in self.sec_user_agent and PLACEHOLDER_CONTACT not in self.sec_user_agent


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    check_checkout()
    return Settings()
