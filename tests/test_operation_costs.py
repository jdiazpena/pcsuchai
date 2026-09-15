"""Actual receipt/log operations; labelled deterministic clocks and owned faults."""

import base64
import gzip
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import pcsuchai.operation_costs as module


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/measure_operation.py"


@pytest.fixture(autouse=True)
def isolated_device(tmp_path, monkeypatch):
    """Isolate test-owned locks without bypassing production exclusion."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))


def receipt(tmp_path, *, terminal=True, status="returned"):
    """Create one native test-owned receipt, not a Pi acceptance campaign."""

    costs = module.OperationCosts(tmp_path / "receipts", "report", scope="complete_locked_public_API_call", context={"fixture": True})
    if terminal:
        costs.finish(status=status, error={"type": "ValueError", "message": "fixture"} if status == "raised" else None)
    return costs


def audit(tmp_path, roots=None):
    """Read raw receipts once and return the persisted audit artifacts."""

    output = tmp_path / "audit"
    result = module.report_operation_costs(roots or [tmp_path / "receipts"], output)
    with gzip.open(output / "operation-costs.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    return result, rows, json.loads((output / "operation-cost-report.json").read_text())


def test_api_timer_result_and_receipts_do_not_mutate_payload(tmp_path, monkeypatch):
    ticks = {"wall": 0., "cpu": 0.}
    def clock():
        return {"captured_utc": "2026-09-15T00:00:00+00:00", "monotonic_seconds": ticks["wall"], "process_cpu_seconds": ticks["cpu"]}
    monkeypatch.setattr(module, "cost_clock", clock)
    @module.measured_operation("report", "output_dir", input_argument="inputs")
    def produce(inputs, output_dir):
        output_dir.mkdir()
        (output_dir / "original.json").write_bytes(b'{"immutable":true}\n')
        ticks.update(wall=4., cpu=2.)
        return {"status": "partial_or_excluded", "report_path": str(output_dir / "original.json")}
    original = tmp_path / "original"
    original.mkdir()
    result = produce(inputs=[original], output_dir=tmp_path / "report")
    costs = result["operation_cost"]
    assert costs["wall_seconds"] == 4. and costs["parent_process_cpu_seconds"] == 2.
    assert costs["status"] == "returned" and costs["outcome"] == "partial_or_excluded"
    assert [path.name for path in (tmp_path / "report").iterdir()] == ["original.json"]
    assert not list(original.iterdir())
    terminal = json.loads((Path(costs["directory"]) / "terminal.json").read_text())
    assert terminal["extra"]["returned_result"]["status"] == "partial_or_excluded"


def test_api_failure_before_output_retains_exception_and_dated_cost(tmp_path):
    @module.measured_operation("import", "destination")
    def fail(destination):
        raise ValueError("original failure")
    with pytest.raises(ValueError, match="original failure"):
        fail(tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()
    terminal = next((tmp_path / "operation-costs").rglob("terminal.json"))
    assert json.loads(terminal.read_text())["status"] == "raised"


@pytest.mark.parametrize("failure", [False, True])
def test_receipt_failure_does_not_hide_error_or_claim_success(tmp_path, monkeypatch, failure):
    commit = module._commit
    def break_terminal(path, value):
        if path.name == "terminal.json":
            raise OSError("test-owned full-disk receipt fault")
        return commit(path, value)
    monkeypatch.setattr(module, "_commit", break_terminal)
    @module.measured_operation("report", "destination")
    def produce(destination):
        if failure:
            raise ValueError("caller failure")
        destination.mkdir()
        return {"status": "done"}
    with pytest.raises(ValueError if failure else OSError) as caught:
        produce(tmp_path / "payload")
    assert list((tmp_path / "operation-costs").rglob("intent.json"))
    assert not list((tmp_path / "operation-costs").rglob("terminal.json"))
    if failure:
        assert "caller failure" in str(caught.value)
        assert any("receipt" in note for note in caught.value.__notes__)
    else:
        assert (tmp_path / "payload").exists()  # Do not silently repeat it.


def test_cost_storage_inside_immutable_input_refused_before_write(tmp_path):
    @module.measured_operation("export", "output", input_argument="source")
    def should_not_run(source, output):
        raise AssertionError("must refuse before running")
    original = tmp_path / "source"
    original.mkdir()
    with pytest.raises(ValueError, match="outside immutable"):
        should_not_run(original, original / "bundle.tar.gz")
    assert not list(original.iterdir())


def test_exclusive_terminal_and_returned_raised_unfinished_accounting(tmp_path):
    first = receipt(tmp_path)
    before = (first.directory / "terminal.json").read_bytes()
    with pytest.raises(FileExistsError):
        first.finish(status="returned")
    assert (first.directory / "terminal.json").read_bytes() == before
    receipt(tmp_path, status="raised")
    receipt(tmp_path, terminal=False)
    result, rows, saved = audit(tmp_path)
    assert result["status"] == "incomplete_or_invalid"
    assert result["counts"] == {"returned": 1, "raised": 1, "unfinished": 1, "invalid": 0}
    assert len(rows) == 3 and len(saved["calls"]) == 2


@pytest.mark.parametrize("fault", ["boolean", "clock", "scope", "units", "identity", "missing_operation", "torn_intent"])
def test_invalid_receipt_retains_both_original_documents(tmp_path, fault):
    costs = receipt(tmp_path)
    ip, tp = costs.directory / "intent.json", costs.directory / "terminal.json"
    intent, terminal = json.loads(ip.read_text()), json.loads(tp.read_text())
    if fault == "boolean": terminal["wall_seconds"] = True
    elif fault == "clock": terminal["wall_seconds"] += 1
    elif fault == "scope": intent["scope"] = "board_power"
    elif fault == "units": intent["units"] = "milliseconds"
    elif fault == "identity": terminal["operation_id"] = "wrong"
    elif fault == "missing_operation": intent.pop("operation")
    if fault == "torn_intent": ip.write_bytes(b'{"torn":')
    else: ip.write_text(json.dumps(intent))
    tp.write_text(json.dumps(terminal))
    raw_intent, raw_terminal = ip.read_bytes(), tp.read_bytes()
    result, rows, saved = audit(tmp_path)
    assert result["counts"]["invalid"] == 1 and not saved["calls"]
    assert base64.b64decode(rows[0]["raw_intent_base64"]) == raw_intent
    assert base64.b64decode(rows[0]["raw_terminal_base64"]) == raw_terminal
    assert ip.read_bytes() == raw_intent and tp.read_bytes() == raw_terminal


def test_overlapping_roots_do_not_double_count_but_copied_identity_is_invalid(tmp_path):
    import shutil
    costs = receipt(tmp_path)
    copied = tmp_path / "copied" / costs.directory.name
    shutil.copytree(costs.directory, copied)
    result, rows, _saved = audit(tmp_path, [tmp_path / "receipts", costs.directory, tmp_path / "copied"])
    assert len(rows) == 2 and result["counts"]["invalid"] == 2


def test_external_wrapper_retains_binary_logs_exit_status_and_containing_scopes(tmp_path):
    command = [sys.executable, "-c", "import os; os.write(1,b'x'*200000); os.write(2,b'error\\xff\\n'); raise SystemExit(7)"]
    run = subprocess.run([sys.executable, str(WRAPPER), "--receipt-root", str(tmp_path / "receipts"), "--quiet", "--", *command], capture_output=True, timeout=30)
    assert run.returncode == 7
    result, rows, saved = audit(tmp_path)
    terminal = rows[0]["terminal"]
    assert result["counts"]["returned"] == 1 and terminal["outcome"]["exit_code"] == 7
    directory = Path(rows[0]["directory"])
    with gzip.open(directory / "stdout.log.gz", "rb") as handle:
        assert handle.read() == b"x" * 200000
    with gzip.open(directory / "stderr.log.gz", "rb") as handle:
        assert handle.read() == b"error\xff\n"
    details = terminal["extra"]
    assert terminal["wall_seconds"] >= details["launch_through_exit"]["wall_seconds"]
    assert details["raw_output_finalization_seconds"] >= 0
    assert details["waited_children_cpu"]["status"] == "available"
    assert details["waited_children_cpu"]["user_seconds"] >= 0
    assert saved["calls"][0]["scope"].startswith("external_command")


def test_external_spawn_failure_has_unknown_child_cost_not_zero(tmp_path):
    run = subprocess.run([sys.executable, str(WRAPPER), "--receipt-root", str(tmp_path / "receipts"), "--", str(tmp_path / "not-a-command")], capture_output=True, timeout=30)
    assert run.returncode != 0
    result, rows, _saved = audit(tmp_path)
    assert result["counts"]["raised"] == 1
    assert rows[0]["terminal"]["extra"]["launch_through_exit"] is None


def test_wrapper_lock_denial_does_not_launch_or_write_observer_data(tmp_path):
    """A competing wrapper cannot do logging I/O inside another benchmark."""

    import os
    from pcsuchai.run_lock import device_run_lock, LOCK_FD_VARIABLE
    with device_run_lock():
        environment = dict(os.environ)
        environment.pop(LOCK_FD_VARIABLE, None)
        run = subprocess.run([sys.executable, str(WRAPPER), "--receipt-root", str(tmp_path / "receipts"), "--", sys.executable, "-c", "pass"],
                             env=environment, capture_output=True, timeout=30)
        assert run.returncode != 0 and b"device already running" in run.stderr
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize("fault", ["launch_wall", "launch_scope", "child_cpu", "finalization"])
def test_external_subclock_tampering_cannot_supply_a_valid_cost_table(tmp_path, fault):
    """Real subprocess receipts are damaged only inside the test-owned tree."""

    run = subprocess.run([sys.executable, str(WRAPPER), "--receipt-root", str(tmp_path / "receipts"), "--quiet", "--", sys.executable, "-c", "pass"], capture_output=True, timeout=30)
    assert run.returncode == 0
    terminal_path = next((tmp_path / "receipts").rglob("terminal.json"))
    terminal = json.loads(terminal_path.read_text())
    if fault == "launch_wall": terminal["extra"]["launch_through_exit"]["wall_seconds"] += 1
    elif fault == "launch_scope": terminal["extra"]["launch_through_exit"]["scope"] = "worker_only"
    elif fault == "child_cpu": terminal["extra"]["waited_children_cpu"]["user_seconds"] = True
    else: terminal["extra"]["raw_output_finalization_seconds"] = -1
    terminal_path.write_text(json.dumps(terminal))
    result, _rows, saved = audit(tmp_path)
    assert result["counts"]["invalid"] == 1 and not saved["calls"]


def test_wrapper_declares_its_observation_variant_in_owned_command_runtime(tmp_path):
    command = [sys.executable, "-c", "from pcsuchai.benchmark import runtime_metadata; import json; print(json.dumps(runtime_metadata()['launch_observation_declaration']))"]
    import os
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    run = subprocess.run([sys.executable, str(WRAPPER), "--receipt-root", str(tmp_path / "receipts"), "--quiet", "--", *command],
                         env=environment, capture_output=True, timeout=30)
    assert run.returncode == 0
    log = next((tmp_path / "receipts").rglob("stdout.log.gz"))
    with gzip.open(log, "rt") as handle:
        marker = json.loads(json.loads(handle.read()))
    assert marker["variant"] == "external_command_tee_v1"
    assert marker["attachment_scope"] == "current_command_until_exit"
    assert marker["raw_log_sync"] == "each_acquired_chunk"


def test_external_wrapper_forwards_graceful_stop_and_saves_terminal(tmp_path):
    ready = tmp_path / "ready"
    command = [sys.executable, "-c", "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); pathlib.Path(sys.argv[1]).touch(); time.sleep(30)", str(ready)]
    child = subprocess.Popen([sys.executable, str(WRAPPER), "--receipt-root", str(tmp_path / "receipts"), "--quiet", "--", *command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            assert child.poll() is None
            time.sleep(.05)
        assert ready.exists()
        child.terminate()
        output, error = child.communicate(timeout=10)
        assert child.returncode == 0, output + error
        _result, rows, _saved = audit(tmp_path)
        assert rows[0]["terminal"]["extra"]["signals_forwarded"]
    finally:
        if child.poll() is None:
            child.terminate()
            child.communicate(timeout=10)
