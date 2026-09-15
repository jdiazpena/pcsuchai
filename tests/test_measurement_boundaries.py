import json
from types import SimpleNamespace

from pcsuchai.benchmark import StreamingExtrema
import pcsuchai.benchmark_suite as suite


def test_streaming_extrema_do_not_accumulate_observations():
    extrema = StreamingExtrema()
    for number in range(100_000):
        extrema.add(number)
    extrema.add(None)
    assert vars(extrema) == {"count": 100_000, "minimum": 0, "maximum": 99_999}


def test_worker_timer_excludes_parent_log_fsync_and_parsing(tmp_path, monkeypatch):
    elapsed = [0.0]

    def fake_launch(command, *, stdout, **kwargs):
        stdout.write(b'{"observations": 3}')
        def wait(timeout=None):
            elapsed[0] += 10
            return 0
        return SimpleNamespace(returncode=0, pid=123, wait=wait, poll=lambda: 0)

    def slow_fsync(_fd):
        elapsed[0] += 5

    monkeypatch.setattr(suite.time, "perf_counter", lambda: elapsed[0])
    monkeypatch.setattr(suite.subprocess, "Popen", fake_launch)
    monkeypatch.setattr(suite.os, "fsync", slow_fsync)
    result, duration, _ = suite._run_child(["python", "--output-dir", str(tmp_path / "products")], 30)
    assert result["observations"] == 3
    assert duration == 10
    timing = json.loads((tmp_path / "child-timing.json").read_text())
    assert timing["worker_launch_to_exit_seconds"] == 10
    assert timing["log_flush_seconds"] == 10
    assert elapsed[0] > duration


def test_cycle_timing_is_committed_after_job_records_without_self_inclusion(tmp_path, monkeypatch):
    elapsed = [30.0]
    write = suite._atomic_write_json

    def slow_commit(path, value):
        elapsed[0] += 5
        write(path, value)

    monkeypatch.setattr(suite.time, "perf_counter", lambda: elapsed[0])
    monkeypatch.setattr(suite, "_atomic_write_json", slow_commit)
    result = suite._commit_cycle_timing(tmp_path, "attempt", 10)
    assert result["full_cycle_seconds"] == 20
    assert elapsed[0] == 35
    run = {"run_id": "attempt", "cycle_timing_path": str(tmp_path / "cycle-timing.json")}
    assert suite._load_run(run)["full_cycle_seconds"] == 20
    missing = suite._load_run({**run, "cycle_timing_path": str(tmp_path / "missing.json")})
    assert missing["full_cycle_seconds"] is None
    assert missing["cycle_timing_status"] == "uncommitted"
