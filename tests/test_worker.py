import io
import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.pipeline import run_analysis
from pcsuchai.worker import PersistentWorker, PersistentWorkerError, serve


ROOT = Path(__file__).resolve().parents[1]


def environment():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def request(directory, number, **options):
    return {
        "request_id": f"attempt-{number}",
        "measurement_path": str(ROOT / "data/raw/langmuir-2018-2.csv"),
        "tle_path": str(ROOT / "data/tle/suchai1.tle"),
        "eop_path": str(ROOT / "data/eop/finals2000A.all"),
        "output_dir": str(directory / f"attempt-{number}" / "products"),
        "orbit_backend": "skyfield", "magnetic_backend": "apexpy",
        "limit": 20, "plot_config_path": None, "benchmark": True,
        **options,
    }


@pytest.mark.parametrize("failure_phase", ["write", "flush"])
def test_completed_native_result_survives_response_pipe_failure(tmp_path, monkeypatch, failure_phase):
    """Real 20-row science with an explicitly injected post-ready transport fault."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))
    messages = []

    class DisconnectedOutput:
        """Accept readiness, then emulate a supervisor closing its response pipe."""

        def write(self, text):
            """Retain attempted messages before raising the injected broken pipe."""
            messages.append(json.loads(text))
            if len(messages) > 1 and failure_phase == "write":
                raise BrokenPipeError("injected response pipe closure")
            return len(text)

        def flush(self):
            """Inject a flush fault after accepting the complete result text."""
            if len(messages) > 1 and failure_phase == "flush":
                raise BrokenPipeError("injected response flush closure")
            return None

    result = serve(io.StringIO(json.dumps(request(tmp_path, 1)) + "\n"), DisconnectedOutput())
    assert result == 2 and len(messages) == 2
    terminal = json.loads((tmp_path / "attempt-1/worker-response.json").read_text())
    incident = json.loads((tmp_path / "attempt-1/worker-delivery-error.json").read_text())
    assert terminal["status"] == "complete" and terminal == messages[1]
    assert incident["failure_class"] == "worker_response_delivery"
    assert incident["request_id"] == terminal["request_id"]
    assert incident["terminal_response_committed"] is True
    assert incident["error_type"] == "BrokenPipeError"
    from pcsuchai.benchmark import sha256_file
    assert incident["terminal_response_sha256"] == sha256_file(tmp_path / "attempt-1/worker-response.json")
    assert incident["publication_attempts"] == 1 and incident["automatic_retry"] is False
    with np.load(terminal["outputs"]["raw_products_npz"], allow_pickle=False) as raw:
        assert len(raw["measurement_source_rows"]) == 20


def test_readiness_pipe_failure_has_no_fabricated_terminal(tmp_path, monkeypatch, capsys):
    """Injected readiness failure is unavailable science, not a zero-duration job."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))

    class ClosedOutput:
        """Emulate a response channel closed before worker readiness."""

        def write(self, text):
            """Reject the first attempted message."""
            raise BrokenPipeError("injected readiness closure")

    assert serve(io.StringIO(""), ClosedOutput()) == 2
    record = json.loads(capsys.readouterr().err)
    assert record["request_id"] is None and record["terminal_response_committed"] is False
    assert record["terminal_response_path"] is record["terminal_response_sha256"] is None
    assert record["publication_attempts"] == 1


def test_existing_publication_incident_cannot_be_overwritten(tmp_path, monkeypatch):
    """Reject the request before production can overwrite an existing incident."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))
    directory = tmp_path / "attempt-1"
    directory.mkdir()
    original = directory / "worker-delivery-error.json"
    original.write_bytes(b"retained original incident")
    output = io.StringIO()
    assert serve(io.StringIO(json.dumps(request(tmp_path, 1)) + "\n"), output) == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert responses[1]["status"] == "protocol_failed"
    assert original.read_bytes() == b"retained original incident"
    assert not (directory / "products").exists()


@pytest.mark.parametrize("orbit_backend,magnetic_backend", [
    ("astropy", "aacgmv2"), ("astropy", "apexpy"),
    ("skyfield", "aacgmv2"), ("skyfield", "apexpy"),
])
def test_persistent_jobs_recompute_same_arrays_and_keep_process_resources_bounded(tmp_path, orbit_backend, magnetic_backend):
    pair = {"orbit_backend": orbit_backend, "magnetic_backend": magnetic_backend}
    first = request(tmp_path, 1, **pair)
    fresh_options = {key: value for key, value in first.items() if key != "request_id"}
    fresh_options["output_dir"] = tmp_path / "fresh"
    fresh = run_analysis(**fresh_options)
    responses = []
    with PersistentWorker(tmp_path / "worker", environment(), timeout_seconds=30) as worker:
        pid = worker.process.pid
        for number in range(1, 4):
            outputs, elapsed, response = worker.execute(request(tmp_path, number, **pair))
            assert elapsed >= response["worker_science_seconds"]
            assert response["pid"] == pid
            assert response["live_figures_before_cleanup"] == 0
            assert not response["reuse"]["measurement_arrays"]
            with np.load(fresh.raw_products_npz, allow_pickle=False) as expected, np.load(outputs["raw_products_npz"], allow_pickle=False) as actual:
                assert expected.files == actual.files
                for key in expected.files:
                    if expected[key].dtype.kind in "fc":
                        assert np.array_equal(expected[key], actual[key], equal_nan=True), key
                    else:
                        assert np.array_equal(expected[key], actual[key]), key
            responses.append(response)
        descriptors = [response["worker_resources_after"]["file_descriptors"]["value"] for response in responses]
        assert max(descriptors) - min(descriptors) <= 1
        memory = [response["worker_resources_after"]["rss_bytes"]["value"] for response in responses]
        # This is a short resource-budget acceptance check after first-use
        # caches, not a claim that a long-running worker cannot leak.
        assert max(memory) - min(memory) < 64 * 1024 * 1024
    assert worker.process.poll() == 0
    assert (tmp_path / "worker/protocol.jsonl").is_file()
    assert all((tmp_path / f"attempt-{n}/worker-response.json").is_file() for n in range(1, 4))


def test_scientific_failure_is_retained_and_does_not_become_a_retry(tmp_path):
    with PersistentWorker(tmp_path / "worker", environment(), timeout_seconds=30) as worker:
        bad = request(tmp_path, 1, tle_path=str(tmp_path / "missing.tle"))
        with pytest.raises(PersistentWorkerError) as caught:
            worker.execute(bad)
        assert caught.value.response["status"] == "failed"
        assert "does not exist" in caught.value.response["error"]
        record = json.loads((tmp_path / "attempt-1/worker-response.json").read_text())
        assert record["request_id"] == "attempt-1"
        assert (tmp_path / "attempt-1/stderr.log").stat().st_size > 0
        outputs, _, result = worker.execute(request(tmp_path, 2))
        assert result["status"] == "complete"
        assert outputs["observations"] == 20


def test_existing_attempt_cannot_be_overwritten(tmp_path):
    existing = tmp_path / "attempt-1/products"
    existing.mkdir(parents=True)
    product = existing / "raw.npz"
    product.write_bytes(b"immutable scientific bytes")
    with PersistentWorker(tmp_path / "worker", environment(), timeout_seconds=30) as worker:
        with pytest.raises(FileExistsError):
            worker.execute(request(tmp_path, 1))
    assert product.read_bytes() == b"immutable scientific bytes"


def test_response_timeout_keeps_live_handle_until_explicit_close(tmp_path):
    with PersistentWorker(tmp_path / "worker", environment(), timeout_seconds=30) as worker:
        worker.timeout_seconds = 0.0001
        with pytest.raises(TimeoutError):
            worker.execute(request(tmp_path, 1, limit=100))
        assert worker.pending
        assert worker.process.poll() is None
        assert (tmp_path / "worker/protocol.jsonl").stat().st_size > 0
    assert worker.process.poll() is not None


def test_malformed_request_is_a_protocol_failure_not_scientific_success():
    output = io.StringIO()
    result = serve(io.StringIO('{"request_id":"broken"}\n'), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert result == 0
    assert responses[0]["kind"] == "ready"
    assert responses[1]["status"] == "protocol_failed"


def test_campaign_uses_one_persistent_worker_and_preserves_compressed_protocol(tmp_path):
    from pcsuchai.benchmark_suite import run_benchmark_suite

    result = run_benchmark_suite(
        tmp_path / "campaign", ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle", ROOT / "data/eop/finals2000A.all",
        orbit_backends=("skyfield",), magnetic_backends=("apexpy",),
        repeats=2, warmups=0, limit=20, selection_method="spread",
        minimum_free_bytes=0, telemetry_interval_seconds=0.05,
        process_mode="persistent", thread_policy="one", project_root=ROOT,
    )
    assert result["status"] == "complete"
    assert result["attempt_counts"]["started"] == 2
    segment = result["process_segments"][0]
    assert segment["mode"] == "persistent"
    exit_record = json.loads(Path(segment["worker_exit_path"]).read_text())
    assert exit_record["return_code"] == 0
    assert not Path(segment["protocol_path"].removesuffix(".gz")).exists()
    with gzip.open(segment["protocol_path"], "rt") as stream:
        messages = [json.loads(line) for line in stream]
    completed = [row["response"] for row in messages if row.get("response", {}).get("status") == "complete"]
    assert len(completed) == 2
    assert {row["pid"] for row in completed} == {segment["pid"]}
    for reference in result["scenarios"]["skyfield-apexpy"]["runs"]:
        record = json.loads(Path(reference["record_path"]).read_text())
        raw = record["artifacts"]["raw_products_npz"]["path"]
        with np.load(raw, allow_pickle=False) as arrays:
            assert arrays["measurement_source_rows"][0] == 2
            assert arrays["measurement_source_rows"][-1] == 26_726
    with gzip.open(result["system_telemetry_segments"][0]["path"], "rt") as stream:
        import csv
        observations = [json.loads(row["observations_json"]) for row in csv.DictReader(stream)]
    assert any(row["worker"].get("rss_bytes", {}).get("value") for row in observations)
