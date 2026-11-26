"""Exclusive lock on `GLINT_RAW_DIR/raw.lock`, so two worktrees never write raw data at once."""

import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from glint.core.errors import GlintError


class LockTimeoutError(GlintError):
    code = "RAW_LOCKED"


@contextmanager
def exclusive_lock(path: Path, *, timeout_s: float = 0, poll_s: float = 0.2) -> Generator[None]:
    """Hold an exclusive advisory lock on `path` for the duration of the block.

    `timeout_s=0` fails immediately if another process holds the lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(
                        f"{path} is held by another process (another worktree downloading?)"
                    ) from None
                time.sleep(poll_s)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def raw_lock(raw_dir: Path, *, timeout_s: float = 0) -> Generator[None]:
    with exclusive_lock(raw_dir / "raw.lock", timeout_s=timeout_s):
        yield
