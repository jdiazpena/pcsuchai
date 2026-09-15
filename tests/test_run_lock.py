import os
import subprocess
import sys
from pathlib import Path

import pytest

from pcsuchai.run_lock import (
    DeviceBusyError, LOCK_FD_VARIABLE, LOCK_PATH_VARIABLE,
    device_run_lock, inherited_lock_fds,
)


PROBE = """
from pcsuchai.run_lock import DeviceBusyError, device_run_lock
try:
    with device_run_lock():
        print('acquired')
except DeviceBusyError:
    raise SystemExit(2)
"""


def environment():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return env


def test_unrelated_launch_is_rejected_but_child_can_inherit(tmp_path, monkeypatch):
    monkeypatch.setenv(LOCK_PATH_VARIABLE, str(tmp_path / "device.lock"))
    with device_run_lock():
        env = environment()
        inherited = subprocess.run(
            [sys.executable, "-c", PROBE], env=env, pass_fds=inherited_lock_fds(),
            capture_output=True, text=True,
        )
        assert inherited.returncode == 0, inherited.stderr
        env.pop(LOCK_FD_VARIABLE)
        contender = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True)
        assert contender.returncode == 2
        # Exiting the inherited child's context must not release its master's lock.
        contender = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True)
        assert contender.returncode == 2
    released = subprocess.run([sys.executable, "-c", PROBE], env=environment(), capture_output=True)
    assert released.returncode == 0


def test_stale_metadata_is_not_a_live_lock(tmp_path, monkeypatch):
    path = tmp_path / "device.lock"
    path.write_text('{"pid": 99999999}')
    monkeypatch.setenv(LOCK_PATH_VARIABLE, str(path))
    with device_run_lock():
        assert inherited_lock_fds()
    assert path.exists()


def test_environment_string_without_descriptor_does_not_grant_access(tmp_path, monkeypatch):
    monkeypatch.setenv(LOCK_PATH_VARIABLE, str(tmp_path / "device.lock"))
    monkeypatch.setenv(LOCK_FD_VARIABLE, "99999999")
    with pytest.raises(DeviceBusyError, match="inherited"):
        with device_run_lock():
            pytest.fail("invalid inheritance was accepted")


def test_actual_master_and_validation_cli_reject_overlap_before_creating_session(tmp_path, monkeypatch):
    monkeypatch.setenv(LOCK_PATH_VARIABLE, str(tmp_path / "device.lock"))
    root = Path(__file__).resolve().parents[1]
    with device_run_lock():
        env = environment()
        env.pop(LOCK_FD_VARIABLE)
        master = subprocess.run([
            sys.executable, str(root / "scripts/run_campaign.py"),
            "--config", "configs/benchmark/quick.json", "--device-label", "busy",
            "--output-root", str(tmp_path / "campaigns"),
        ], env=env, capture_output=True, text=True)
        assert master.returncode == 2
        assert "already running" in master.stderr
        validation = subprocess.run([
            sys.executable, "-m", "pcsuchai", "validate-full", "--output-dir", str(tmp_path / "validation"),
        ], env=env, capture_output=True, text=True)
        assert validation.returncode == 2
        assert "already running" in validation.stderr
        assert not (tmp_path / "campaigns").exists()
        assert not (tmp_path / "validation").exists()
