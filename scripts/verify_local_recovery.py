#!/usr/bin/env python3
"""LOCAL fault evidence: an owned supervisor SIGKILL, native exit and resume.

This is not a Pi benchmark or a power-failure guarantee. All raw products,
partial journals, subprocess logs and inventories remain in dated directories.
Only a process launched here, or its verified worker identity, may be signalled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and not sys.flags.no_user_site:
    os.execv(sys.executable, [sys.executable, "-s", *sys.argv])
sys.path.insert(0, str(ROOT / "src"))

from pcsuchai.experiment import ExperimentManifest
from pcsuchai.experiment_control import identity_is_live, process_identity
from pcsuchai.experiment_report import report_experiments
from pcsuchai.retention import compress_retained_file
from pcsuchai.run_lock import LOCK_FD_VARIABLE
from pcsuchai.saved_attempts import _json


def _commit(path: Path, value: dict) -> None:
    """Exclusively retain metadata; existing or torn evidence is never replaced."""

    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _inventory(directory: Path) -> dict:
    """Hash every original orphan byte after its verified worker has exited."""

    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


def _wait(predicate, *, timeout: float, child=None):
    """Poll a specific condition/owned handle; timeout never restarts a process."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        if child is not None and child.poll() is not None:
            raise RuntimeError(f"owned supervisor exited before observed condition: {child.returncode}")
        time.sleep(0.02)
    raise TimeoutError("local recovery observation expired; no automatic relaunch")


def _owned_worker_identity(checkpoint: Path, supervisor_pid: int):
    """Bind a live native worker to this owned supervisor, not a stale journal PID."""

    segments = _json(checkpoint).get("process_segments", [])
    if not segments:
        return None
    pid = segments[-1].get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    identity = process_identity(pid)
    if not identity_is_live(identity):
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        parent_pid = int(fields[1])
    except (OSError, ValueError, IndexError):
        return None
    if parent_pid != supervisor_pid or not identity_is_live(identity):
        return None
    return identity


def _owned_worker(campaign: Path, supervisor_pid: int):
    """Observe only a worker whose actual parent is the supplied owned handle."""

    for checkpoint in campaign.glob("sessions/*/*/benchmark-session.checkpoint.json"):
        identity = _owned_worker_identity(checkpoint, supervisor_pid)
        if identity is not None:
            return identity
    return None


def _active_job(campaign: Path, supervisor_pid: int):
    """Require a durable intent and actual production output, not only heartbeat."""

    for heartbeat in campaign.glob("sessions/*/*/heartbeat.json"):
        row = _json(heartbeat)
        if row.get("phase") != "measured" or not row.get("run_directory"):
            continue
        directory = Path(row["run_directory"])
        if not directory.resolve().is_relative_to(campaign.resolve()):
            raise ValueError("observed attempt escapes owned campaign")
        if (directory / "attempt-intent.json").is_file() and any((directory / "products").glob("*.csv")):
            if (directory / "run-record.json").exists() or (directory / "worker-response.json").exists():
                continue
            identity = _owned_worker_identity(
                heartbeat.parent / "benchmark-session.checkpoint.json", supervisor_pid)
            if identity is not None:
                return directory, identity
    return None


def _cleanup_owned(children, identities) -> None:
    """Stop exact launched handles/verified workers without hiding a prior fault."""

    prior_error = sys.exception()
    errors = []
    for child in children:
        if child is not None:
            try:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
            except Exception as exc:
                errors.append(exc)
    for identity in identities:
        if identity is not None:
            try:
                if identity_is_live(identity):
                    try:
                        os.kill(identity["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # it exited between the verified observation and signal
                    _wait(lambda: not identity_is_live(identity), timeout=10)
            except Exception as exc:
                errors.append(exc)
    if errors:
        if prior_error is not None:
            for error in errors:
                prior_error.add_note(f"owned-process cleanup failed: {type(error).__name__}: {error}")
        else:
            raise ExceptionGroup("owned-process cleanup failures", errors)


def run_case(output_root: Path, mode: str) -> dict:
    """Run one real fixed/timed fault scenario with full raw retention and audit."""

    if mode not in ("fixed", "timed"):
        raise ValueError("local recovery mode must be fixed or timed")
    if os.environ.get(LOCK_FD_VARIABLE) is not None:
        raise ValueError("run local recovery directly, not under an inherited benchmark-lock wrapper")
    now = datetime.now(timezone.utc)
    folder = (output_root.resolve() / now.strftime("%Y/%m/%d") /
              f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{mode}-{uuid4().hex[:8]}")
    folder.mkdir(parents=True, exist_ok=False)
    _commit(folder / "intent.json", {"created_utc": now.isoformat(), "mode": mode,
        "classification": "local_native_fault_workflow_not_Pi_acceptance_or_performance",
        "fault": "SIGKILL only the owned supervisor after observing native CSV output",
        "power_failure_guarantee": False})
    data = _json(ROOT / "configs/experiments/persistent.json")
    data.update(name=f"local-abrupt-{mode}-not-Pi-acceptance", sessions=1)
    data["workload"].update(pairs=["skyfield-apexpy"], selection={"method": "spread", "sizes": [100]},
        plot_profiles=[{"name": "archive-full", "config": "configs/plots/archive-full.json"}])
    data["execution"].update(stop={"kind": "attempts_per_pair" if mode == "fixed" else "duration_per_pair_seconds",
                                   "value": 4 if mode == "fixed" else 2}, warmups=0,
                              failure_policy="continue", timeout_seconds=90)
    data["thermal"].update(mode="uncontrolled", policy=None, maximum_temperature_c=None)
    data["observation"]["board_interval_seconds"] = 0.1
    data["retention"]["minimum_free_bytes"] = 0
    data["validation"]["require_full_certificate"] = False
    model = ExperimentManifest.from_dict(data)
    _commit(folder / "requested-manifest.json", model.data)
    campaign = folder / "campaign"
    environment = dict(os.environ)
    # Each real master owns its normal device lock. Do not inherit a caller's
    # reentrant token: another master/old worker must actually block a launch.
    command = [sys.executable, str(ROOT / "scripts/run_experiment.py"), "run", "--manifest",
               str(folder / "requested-manifest.json"), "--device-label", "local-native-fault",
               "--session-dir", str(campaign)]
    child, resumed, worker_identity, resumed_worker_identity, orphan = None, None, None, None, None
    try:
        with (folder / "launch.stdout.log").open("xb") as stdout, (folder / "launch.stderr.log").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr, start_new_session=True)
            orphan, worker_identity = _wait(lambda: _active_job(campaign, child.pid), timeout=60, child=child)
            _commit(folder / "fault-boundary.json", {"supervisor_identity": process_identity(child.pid),
                "worker_identity": worker_identity, "orphan_directory": str(orphan),
                "observed_production_files": [path.name for path in (orphan / "products").glob("*")],
                "observed_utc": datetime.now(timezone.utc).isoformat()})
            child.kill()  # exact subprocess handle launched above, never a stale arbitrary PID
            child.wait(timeout=10)
            _wait(lambda: not identity_is_live(worker_identity), timeout=60)
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
        original = _inventory(orphan)
        _commit(folder / "orphan-original-inventory.json", original)
        terminal = _json(orphan / "worker-response.json")
        delivery = _json(orphan / "worker-delivery-error.json")
        if terminal["status"] != "complete" or not delivery["terminal_response_committed"]:
            raise ValueError("native completed terminal/delivery incident was not preserved")
        with (folder / "resume.stdout.log").open("xb") as stdout, (folder / "resume.stderr.log").open("xb") as stderr:
            resumed = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_experiment.py"), "resume", str(campaign)],
                                       cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)

            def observe_resume():
                """Track the resumed native child's identity until its owned parent exits."""
                nonlocal resumed_worker_identity
                identity = _owned_worker(campaign, resumed.pid)
                if identity is not None:
                    resumed_worker_identity = identity
                return resumed.poll() is not None

            _wait(observe_resume, timeout=90)
            resumed.wait(timeout=10)
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
        after = _inventory(orphan)
        if any(after.get(name) != digest for name, digest in original.items()):
            raise ValueError("resume changed an original orphan byte")
        recovered = _json(orphan / "reconciliation-record.json")
        state = _json(campaign / "experiment-state.json")
        counts = state["attempt_counts"]
        if recovered["status"] != "interrupted" or recovered["timing_status"] != "unavailable_uncommitted":
            raise ValueError("unconfirmed slot was falsely upgraded or elapsed time fabricated")
        if counts["interrupted"] != 1 or counts["automatic_retries"] != 0:
            raise ValueError("original interrupted attempt disappeared or was silently retried")
        if mode == "fixed":
            if (counts["scheduled"] != 4 or counts["started"] != 4 or counts["scientifically_valid"] != 3
                    or state["status"] != "complete" or resumed.returncode != 0):
                raise ValueError(f"fixed-work resume did not preserve exact attempt accounting: {counts}")
        else:
            blocks = list(campaign.glob("sessions/*/*/benchmark-session.json"))
            if (counts["started"] != 1 or counts["scientifically_valid"] != 0 or state["status"] != "stopped"
                    or resumed.returncode != 2 or len(blocks) != 1
                    or _json(blocks[0]).get("duration_clock_status") != "unavailable_after_abrupt_uncommitted_segment"):
                raise ValueError("timed resume restarted work despite unavailable duration budget")
        report = report_experiments([campaign], folder / "saved-report")
        if report["status"] != "partial_or_excluded" or report["attempt_counts"]["interrupted"] != 1:
            raise ValueError("saved report hid the interruption")
        for name in ("launch.stdout.log", "launch.stderr.log", "resume.stdout.log", "resume.stderr.log"):
            compress_retained_file(folder / name, remove_original=True)
        result = {"status": "pass", "mode": mode, "folder": str(folder), "counts": counts,
                  "supervisor_exit_code": child.returncode, "resume_exit_code": resumed.returncode,
                  "original_orphan_files_preserved": len(original), "reconciliation": recovered,
                  "saved_report": report, "classification": "local_native_fault_workflow_not_Pi_acceptance_or_performance"}
        _commit(folder / "result.json", result)
        return result
    except BaseException as exc:
        # Keep the actual failed check and any still-live identity; observation
        # expiry is not fabricated exit evidence. Cleanup below is explicit.
        try:
            _commit(folder / "failure.json", {"status": "failed", "mode": mode,
                "failed_utc": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__, "error": str(exc),
                "observed_supervisor_exit_code": child.poll() if child is not None else None,
                "observed_resume_exit_code": resumed.poll() if resumed is not None else None,
                "worker_identity": worker_identity, "resumed_worker_identity": resumed_worker_identity,
                "automatic_relaunch": False,
                "raw_records_pruned": False})
        except BaseException as persistence_error:
            exc.add_note(f"failure metadata could not be retained at {folder}: {persistence_error}")
        raise
    finally:
        # Fault-test cleanup is limited to our exact owned handle/verified child.
        # No product, log, intent, snapshot or partial record is deleted.
        _cleanup_owned((child, resumed), (worker_identity, resumed_worker_identity))


def main() -> int:
    """Run requested local scenarios once and print their retained evidence roots."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/verification/abrupt-recovery-workflow")
    parser.add_argument("--mode", choices=("fixed", "timed", "both"), default="both")
    arguments = parser.parse_args()
    results = [run_case(arguments.output_root, mode) for mode in
               (("fixed", "timed") if arguments.mode == "both" else (arguments.mode,))]
    print(json.dumps(results, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
