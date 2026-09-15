"""Safety checks for the LOCAL fault driver; synthetic faults are explicit."""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "local_recovery_workflow", Path(__file__).resolve().parents[1] / "scripts/verify_local_recovery.py")
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


@pytest.mark.parametrize("mode,inherited", [("invalid", False), ("fixed", True)])
def test_invalid_launch_is_rejected_before_creating_evidence(tmp_path, monkeypatch, mode, inherited):
    """Invalid protocol/inherited ownership cannot create or launch a campaign."""

    monkeypatch.delenv(workflow.LOCK_FD_VARIABLE, raising=False)
    if inherited:
        monkeypatch.setenv(workflow.LOCK_FD_VARIABLE, "123")
    monkeypatch.setattr(workflow.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("unexpected launch"))
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        workflow.run_case(output, mode)
    assert not output.exists()


def test_exited_handle_is_terminal_not_a_relaunch_request():
    """A synthetic terminal handle is observed once and never restarted."""

    child = SimpleNamespace(poll=lambda: 17, returncode=17)
    with pytest.raises(RuntimeError, match="supervisor exited.*17"):
        workflow._wait(lambda: None, timeout=1, child=child)


def test_observation_expiry_does_not_establish_process_exit():
    """A synthetic expired observation carries no inferred child return code."""

    child = SimpleNamespace(poll=lambda: None, returncode=None)
    with pytest.raises(TimeoutError, match="no automatic relaunch"):
        workflow._wait(lambda: None, timeout=0, child=child)
    assert child.returncode is None


def test_active_attempt_cannot_escape_owned_campaign(tmp_path):
    """A forged heartbeat path is rejected before any outside output is read."""

    campaign = tmp_path / "campaign"
    heartbeat = campaign / "sessions/session-0001/block-0001/heartbeat.json"
    heartbeat.parent.mkdir(parents=True)
    workflow._commit(heartbeat, {"phase": "measured", "run_directory": str(tmp_path / "outside")})
    with pytest.raises(ValueError, match="escapes owned campaign"):
        workflow._active_job(campaign, os.getpid())


def test_worker_identity_requires_actual_owned_parent(tmp_path):
    """Real Linux identity lookup cannot accept the same PID under a false parent."""

    checkpoint = tmp_path / "checkpoint.json"
    workflow._commit(checkpoint, {"process_segments": [{"pid": os.getpid()}]})
    identity = workflow._owned_worker_identity(checkpoint, os.getppid())
    assert identity["pid"] == os.getpid()
    assert workflow._owned_worker_identity(checkpoint, -1) is None


@pytest.mark.parametrize("pid", [True, False, -1, 0, "123", None])
def test_malformed_journal_pid_never_becomes_signal_authority(tmp_path, monkeypatch, pid):
    """Synthetic invalid PIDs are rejected before process identity acquisition."""

    checkpoint = tmp_path / "checkpoint.json"
    workflow._commit(checkpoint, {"process_segments": [{"pid": pid}]})
    monkeypatch.setattr(workflow, "process_identity", lambda *args: pytest.fail("invalid PID inspected"))
    assert workflow._owned_worker_identity(checkpoint, 123) is None


def test_launch_failure_retains_intent_raw_logs_and_unknown_exit(tmp_path, monkeypatch):
    """An injected launch error retains failure evidence, without imaginary work."""

    monkeypatch.delenv(workflow.LOCK_FD_VARIABLE, raising=False)

    def cannot_launch(*args, **kwargs):
        """Inject an OS launch failure before any child exists."""
        raise OSError("injected local supervisor launch failure")

    monkeypatch.setattr(workflow.subprocess, "Popen", cannot_launch)
    with pytest.raises(OSError, match="injected local supervisor"):
        workflow.run_case(tmp_path, "fixed")
    failures = list(tmp_path.rglob("failure.json"))
    assert len(failures) == 1
    folder = failures[0].parent
    failure = json.loads(failures[0].read_text())
    assert failure["observed_supervisor_exit_code"] is None
    assert failure["observed_resume_exit_code"] is None
    assert failure["automatic_relaunch"] is False and failure["raw_records_pruned"] is False
    assert (folder / "intent.json").is_file() and (folder / "requested-manifest.json").is_file()
    assert (folder / "launch.stdout.log").is_file() and (folder / "launch.stderr.log").is_file()
    assert not (folder / "result.json").exists()


def test_cleanup_tracks_both_owned_handles_and_rejects_stale_identity(monkeypatch):
    """Synthetic owned launch/resume handles are stopped, but no stale PID is."""

    calls = []

    def handle(name):
        """Build an explicitly synthetic live Popen-like handle."""
        return SimpleNamespace(poll=lambda: None, kill=lambda: calls.append((name, "kill")),
                               wait=lambda timeout: calls.append((name, "wait", timeout)))

    monkeypatch.setattr(workflow, "identity_is_live", lambda identity: False)
    monkeypatch.setattr(workflow.os, "kill", lambda *args: pytest.fail("stale worker signalled"))
    workflow._cleanup_owned((handle("launch"), handle("resume")), ({"pid": 123}, None))
    assert calls == [("launch", "kill"), ("launch", "wait", 10),
                     ("resume", "kill"), ("resume", "wait", 10)]


def test_cleanup_error_does_not_replace_original_fault():
    """An injected cleanup error is appended to the actual observation failure."""

    def cannot_kill():
        """Inject a cleanup permission failure."""
        raise PermissionError("injected cleanup denied")

    child = SimpleNamespace(poll=lambda: None, kill=cannot_kill)
    try:
        raise TimeoutError("original observed timeout")
    except TimeoutError as original:
        workflow._cleanup_owned((child,), ())
        assert str(original) == "original observed timeout"
        assert "injected cleanup denied" in original.__notes__[0]
