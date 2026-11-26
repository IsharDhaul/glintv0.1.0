import subprocess
import sys
from pathlib import Path

import pytest

from glint.core.filelock import LockTimeoutError, raw_lock


def test_second_holder_is_refused(tmp_path: Path) -> None:
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time, pathlib\n"
            "from glint.core.filelock import raw_lock\n"
            f"with raw_lock(pathlib.Path({str(tmp_path)!r})):\n"
            "    print('locked', flush=True)\n"
            "    time.sleep(10)\n",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(LockTimeoutError), raw_lock(tmp_path, timeout_s=0.3):
            pass
    finally:
        holder.kill()
        holder.wait()
    with raw_lock(tmp_path):
        assert (tmp_path / "raw.lock").exists()
