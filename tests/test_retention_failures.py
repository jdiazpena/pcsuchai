"""Real native science with explicitly injected parent retention failures."""

import errno
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import numpy as np
import pytest

import pcsuchai.benchmark_suite as suite
from pcsuchai.worker import AnalysisExecutor, managed_analysis_execution


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("kind", ["measured", "warmup"])
@pytest.mark.parametrize("process_mode", ["fresh", "persistent"])
def test_native_retention_disk_failure_keeps_raw_and_consumes_only_its_slot(tmp_path, monkeypatch, kind, process_mode):
    """Inject ENOSPC only at the first closed stdout compression, after real science."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))
    original = suite.compress_retained_file
    failures = []

    def disk_full_at_attempt_stdout(path, **options):
        """Keep the original bytes and emulate one parent-side storage failure."""
        path = Path(path)
        if path.name == "stdout.log" and not failures:
            failures.append(path)
            raise OSError(errno.ENOSPC, "injected attempt compression disk exhaustion")
        return original(path, **options)

    monkeypatch.setattr(suite, "compress_retained_file", disk_full_at_attempt_stdout)
    result = suite.run_benchmark_suite(
        tmp_path / "benchmark", ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle", ROOT / "data/eop/finals2000A.all",
        scenario_pairs=("skyfield-apexpy",), repeats=2, warmups=1 if kind == "warmup" else 0,
        limit=20, selection_method="spread", project_root=ROOT,
        minimum_free_bytes=0, continue_on_error=True, telemetry_interval_seconds=0.1,
        timeout_seconds=60,
        process_mode=process_mode,
    )
    assert result["status"] == "stopped" and "retention failure" in result["stop_reason"]
    assert len(failures) == 1 and failures[0].is_file()
    record = json.loads((failures[0].parent / "run-record.json").read_text())
    assert record["status"] == "failed" and record["failure_class"] == "disk_exhaustion"
    assert record["failure_phase"] == "retention" and record["scientific_execution_status"] == "complete"
    assert record["storage"]["status"] == "failed" and record["storage"]["retention_completed"] is False
    assert record["storage"]["retention_failure"]["error_errno"] == errno.ENOSPC
    assert record["storage"]["retention_wall_seconds"] >= 0
    assert result["attempt_counts"]["automatic_retries"] == 0
    assert result["attempt_counts"]["scientifically_valid"] == 0
    assert result["attempt_counts"]["started"] == (1 if kind == "measured" else 0)
    assert result["attempt_counts"]["failed"] == (1 if kind == "measured" else 0)
    assert result["attempt_counts"]["skipped"] == (1 if kind == "measured" else 2)
    assert len(result["execution_order"]) == 1 and result["execution_order"][0]["kind"] == kind
    assert len(result["failures"]) == 1 and not result["scenarios"]["skyfield-apexpy"]["runs"]
    products = failures[0].parent / "products"
    raw = next(products.glob("*.npz"))
    with np.load(raw, allow_pickle=False) as arrays:
        assert len(arrays["measurement_source_rows"]) == 20
    assert len(list(products.glob("*.png"))) == 3
    assert (failures[0].parent / "attempt-intent.json").is_file()
    assert len(list((tmp_path / "benchmark/runs").glob("*/*"))) == (1 if kind == "measured" else 0)


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_secondary_retention_failure_does_not_replace_primary_fault(tmp_path, monkeypatch, status):
    """Synthetic secondary storage error retains the distinct primary cause."""

    def disk_full(*args):
        """Inject retention exhaustion without executing or altering any science."""
        raise OSError(errno.ENOSPC, "injected secondary retention fault")

    monkeypatch.setattr(suite, "_retain_run", disk_full)
    record = {"status": status, "error_type": "OriginalError", "error": "original cause", "failure_class": "worker_protocol"}
    assert suite._retain_attempt(record, tmp_path, tmp_path) is False
    assert record["status"] == status and record["error_type"] == "OriginalError"
    assert record["error"] == "original cause" and record["failure_class"] == "worker_protocol"
    assert record["retention_failure"]["failure_class"] == "disk_exhaustion"


@pytest.mark.parametrize("process_mode", ["fresh", "persistent"])
def test_unwritable_terminal_stops_sampler_and_resumes_without_invented_success(tmp_path, monkeypatch, process_mode):
    """Real native output plus an injected terminal-write ENOSPC preserves an orphan."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))
    original_commit = suite._atomic_write_json
    original_init = suite._TelemetryJournal.__init__
    samplers, faults = [], []

    def capture_sampler(self, *args, **kwargs):
        """Track the actual recorder for the exception-exit cleanup assertion."""
        original_init(self, *args, **kwargs)
        samplers.append(self)

    def no_terminal_space(path, value):
        """Inject one terminal failure, leaving real raw product bytes intact."""
        if Path(path).name == "run-record.json" and not faults:
            faults.append(Path(path))
            raise OSError(errno.ENOSPC, "injected terminal commit disk exhaustion")
        return original_commit(path, value)

    monkeypatch.setattr(suite._TelemetryJournal, "__init__", capture_sampler)
    monkeypatch.setattr(suite, "_atomic_write_json", no_terminal_space)
    options = dict(scenario_pairs=("skyfield-apexpy",), repeats=2, warmups=0,
                   limit=20, selection_method="spread", project_root=ROOT,
                   minimum_free_bytes=0, telemetry_interval_seconds=0.1,
                   timeout_seconds=60, process_mode=process_mode)
    inputs = (tmp_path / "benchmark", ROOT / "data/raw/langmuir-2018-2.csv",
              ROOT / "data/tle/suchai1.tle", ROOT / "data/eop/finals2000A.all")
    try:
        with pytest.raises(OSError, match="injected terminal commit"):
            suite.run_benchmark_suite(*inputs, **options)
        assert samplers and all(not sampler.thread.is_alive() for sampler in samplers)
        orphan = faults[0].parent
        assert not faults[0].exists() and (orphan / "attempt-intent.json").exists()
        before = {path.relative_to(orphan): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in orphan.rglob("*") if path.is_file()}
        recovered = suite.run_benchmark_suite(*inputs, **options, resume=True)
        assert recovered["attempt_counts"]["started"] == 2
        assert recovered["attempt_counts"]["interrupted"] == 1
        assert recovered["attempt_counts"]["scientifically_valid"] == 1
        assert recovered["attempt_counts"]["automatic_retries"] == 0
        assert all(hashlib.sha256((orphan / name).read_bytes()).hexdigest() == digest for name, digest in before.items())
        reconciliation = json.loads((orphan / "reconciliation-record.json").read_text())
        assert reconciliation["status"] == "interrupted" and reconciliation["timing_status"] == "unavailable_uncommitted"
    finally:
        # Explicit test-owned recorder cleanup is needed to contain the pre-fix
        # failure; production must release it itself before resume is permitted.
        for sampler in samplers:
            if sampler.thread is not None and sampler.thread.is_alive():
                sampler.stop()


def test_sampler_stop_is_idempotent_even_after_unwritable_final_sample(tmp_path, monkeypatch):
    """Synthetic final-sample ENOSPC joins the owned thread without a second write."""

    journal = suite._TelemetryJournal(tmp_path / "raw.csv", tmp_path, 0.1)
    journal.thread = threading.Thread(target=lambda: journal.stop_event.wait(10))
    journal.thread.start()
    calls = []

    def cannot_save():
        """Inject a write failure after the recorder's thread is joined."""
        calls.append(1)
        raise OSError(errno.ENOSPC, "injected final sample full disk")

    monkeypatch.setattr(journal, "sample", cannot_save)
    with pytest.raises(OSError, match="injected final sample"):
        journal.stop()
    assert journal.stopped and not journal.thread.is_alive()
    journal.stop()
    assert calls == [1]


def test_stream_retention_failure_is_not_implicitly_retried(tmp_path, monkeypatch):
    """Synthetic stream retention failure runs campaign cleanup only once."""

    executor = AnalysisExecutor("persistent")
    calls = []
    executor.manage_cleanup(lambda: calls.append("recorder-stopped"))
    executor.worker = SimpleNamespace(close=lambda: calls.append("worker-close"),
                                     journal_path=tmp_path / "protocol.jsonl", directory=tmp_path)

    def cannot_compress(*args, **kwargs):
        """Inject log compression exhaustion without touching any payload."""
        calls.append("compression-attempt")
        raise OSError(errno.ENOSPC, "injected stream full disk")

    monkeypatch.setattr("pcsuchai.retention.compress_retained_file", cannot_compress)
    with pytest.raises(OSError, match="injected stream"):
        executor.close()
    executor.close()
    assert calls == ["recorder-stopped", "worker-close", "compression-attempt", "worker-close"]
    assert executor.stream_retention_attempted and executor.retained_streams is None


def test_campaign_cleanup_error_is_attached_to_original_exception():
    """Synthetic recorder cleanup cannot replace the primary ENOSPC exception."""

    def cleanup_failure():
        """Inject a separate cleanup failure."""
        raise RuntimeError("injected recorder cleanup failure")

    @managed_analysis_execution
    def failing_campaign(*, _executor=None):
        """Register a resource before injecting the primary storage fault."""
        _executor.manage_cleanup(cleanup_failure)
        raise OSError(errno.ENOSPC, "original terminal commit failure")

    with pytest.raises(OSError, match="original terminal commit") as error:
        failing_campaign()
    assert "injected recorder cleanup failure" in error.value.__notes__[0]
