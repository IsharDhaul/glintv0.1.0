"""Build-then-swap: the pointer flip and build retention (SPEC §4.2, §4.7).

A build is written to `data/builds/<build_id>.duckdb`. Only after every stage succeeded does
`current.json` change, by writing a temp file and `os.replace`-ing it over the old one, so a
reader sees the old pointer or the new one, never half of either. A killed run leaves the old
pointer, and the API keeps serving the old build.

Retention: the new build and the one it replaced. Everything else in `builds/` (older builds,
failed or killed runs) is deleted after a successful publish. `user.duckdb` lives outside
`builds/` and is never opened, listed or deleted here.
"""

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from glint.contracts.db import DB_SCHEMA_VERSION, CurrentPointer
from glint.core.errors import ContractError
from glint.core.paths import Paths

KEEP_BUILDS = 2


def read_pointer(paths: Paths) -> CurrentPointer | None:
    p = paths.current_pointer
    if not p.exists():
        return None
    try:
        return CurrentPointer.model_validate_json(p.read_text())
    except (ValidationError, ValueError) as exc:
        raise ContractError(f"{p} is unreadable: fix or delete it, then rerun") from exc


def pointer_db(paths: Paths, pointer: CurrentPointer) -> Path:
    return paths.db_dir / pointer.path


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_pointer(paths: Paths, build_id: str, created_at: datetime) -> CurrentPointer:
    """Point current.json at `builds/<build_id>.duckdb`, atomically."""
    pointer = CurrentPointer(
        build_id=build_id,
        path=str(paths.build_db(build_id).relative_to(paths.db_dir)),
        db_schema_version=DB_SCHEMA_VERSION,
        synthetic=False,
        created_at=created_at.astimezone(UTC),
    )
    target = paths.current_pointer
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with tmp.open("w") as fh:
        fh.write(pointer.model_dump_json(indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(target)  # os.replace: atomic on POSIX
    _fsync_dir(target.parent)
    return pointer


def seed_from(src: Path, dst: Path) -> None:
    """Start a partial (--only / --from) build as a copy of the current one; never in place."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".seed")
    shutil.copyfile(src, tmp)
    tmp.replace(dst)


def _build_files(paths: Paths) -> dict[str, list[Path]]:
    """build_id → its files (the .duckdb plus any .wal / .seed leftovers)."""
    out: dict[str, list[Path]] = {}
    if not paths.builds_dir.exists():
        return out
    for f in paths.builds_dir.iterdir():
        build_id = f.name.split(".duckdb", 1)[0]
        if f.is_file() and ".duckdb" in f.name:
            out.setdefault(build_id, []).append(f)
    return out


def prune_builds(paths: Paths, keep: set[str]) -> list[str]:
    """Delete every build in `builds/` whose id isn't in `keep`. Returns the deleted ids."""
    removed: list[str] = []
    for build_id, files in sorted(_build_files(paths).items()):
        if build_id in keep:
            continue
        for f in files:
            f.unlink(missing_ok=True)
        removed.append(build_id)
    return removed
