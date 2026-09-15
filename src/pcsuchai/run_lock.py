"""One advisory device lock shared by benchmark masters and their subprocesses."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path


LOCK_FD_VARIABLE = "PCSUCHAI_RUN_LOCK_FD"
LOCK_PATH_VARIABLE = "PCSUCHAI_RUN_LOCK_PATH"


class DeviceBusyError(RuntimeError):
    """Another process already owns the device's benchmark/validation lock."""


def _lock_path() -> Path:
    """Use one path across repositories; explicit override supports isolated tests."""

    return Path(os.environ.get(LOCK_PATH_VARIABLE, "/tmp/pcsuchai-benchmark.lock")).resolve()


def inherited_lock_fds(environment: dict[str, str] | None = None) -> tuple[int, ...]:
    """Verify the descriptor supplied to subprocess ``pass_fds`` on Linux.

    An environment string alone grants no ownership. The open descriptor must
    identify the exact regular lock file and hold the exclusive flock.
    """

    env = os.environ if environment is None else environment
    raw = env.get(LOCK_FD_VARIABLE)
    if raw is None:
        return ()
    try:
        fd = int(raw)
        path = Path(env.get(LOCK_PATH_VARIABLE, "/tmp/pcsuchai-benchmark.lock")).resolve()
        info = os.fstat(fd)
        target = path.stat()
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (target.st_dev, target.st_ino):
            raise ValueError("descriptor does not identify the run lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError) as exc:
        raise DeviceBusyError("invalid or unavailable inherited run-lock descriptor") from exc
    return (fd,)


@contextmanager
def device_run_lock():
    """Acquire the common lock or reuse inheritance without unlocking the master.

    The OS releases ownership after the last descriptor closes; stale metadata
    cannot keep the board locked. Never remove or replace this inode. Child
    launches propagate ownership with ``inherited_lock_fds``.
    """

    if inherited_lock_fds():
        yield
        return
    path = _lock_path()
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o666)
    previous_path = os.environ.get(LOCK_PATH_VARIABLE)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            owner = os.pread(fd, 4096, 0).decode("utf-8", errors="replace")
            raise DeviceBusyError(f"device already running a benchmark or validation; owner: {owner.strip()}") from exc
        if os.fstat(fd).st_uid == os.getuid():
            os.fchmod(fd, 0o666)
        owner = json.dumps({
            "pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "device", "path": str(path),
        }).encode("utf-8")
        os.ftruncate(fd, 0)
        os.write(fd, owner)
        os.fsync(fd)
        os.environ[LOCK_FD_VARIABLE] = str(fd)
        os.environ[LOCK_PATH_VARIABLE] = str(path)
        yield
    finally:
        os.environ.pop(LOCK_FD_VARIABLE, None)
        if previous_path is None:
            os.environ.pop(LOCK_PATH_VARIABLE, None)
        else:
            os.environ[LOCK_PATH_VARIABLE] = previous_path
        os.close(fd)


def serialized_run(function):
    """Give a public benchmark/validation API the same lock as its CLI caller."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with device_run_lock():
            return function(*args, **kwargs)

    return wrapped
