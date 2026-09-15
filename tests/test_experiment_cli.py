import json
import os
import subprocess
import sys
import time
from pathlib import Path

from pcsuchai.experiment_control import experiment_status, identity_is_live


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "scripts/run_experiment.py"


def invoke(arguments, environment):
    return subprocess.run([sys.executable, str(MASTER), *arguments], env=environment,
                          capture_output=True, text=True, timeout=90)


def test_real_detached_stop_resume_keeps_attempts_and_protocol(tmp_path, monkeypatch):
    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "test-device.lock"))
    environment = dict(os.environ)
    data = json.loads((ROOT / "configs/experiments/persistent.json").read_text())
    data["name"] = "test-persistent"
    data["sessions"] = 1
    data["workload"]["pairs"] = ["skyfield-apexpy"]
    data["workload"]["selection"] = {"method": "spread", "sizes": [20]}
    data["workload"]["plot_profiles"] = [{"name": "minimal", "config": None}]
    data["execution"].update(stop={"kind": "attempts_per_pair", "value": 6}, warmups=0)
    data["thermal"].update(mode="uncontrolled", policy=None, maximum_temperature_c=None)
    data["retention"]["minimum_free_bytes"] = 0
    data["observation"]["board_interval_seconds"] = 0.1
    data["validation"]["require_full_certificate"] = False
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    launched = invoke(["run", "--manifest", str(manifest), "--device-label", "local-test",
                       "--output-root", str(tmp_path / "experiments"), "--detach"], environment)
    assert launched.returncode == 0, launched.stdout + launched.stderr
    record = json.loads(launched.stdout.split("\n", 1)[1])
    assert record["ready"]
    directory = Path(record["directory"])
    deadline = time.monotonic() + 60
    # Request stop while a complete real production job is active. Status can
    # observe the true worker boundary via its raw heartbeat, not a fake sleep.
    active = None
    while time.monotonic() < deadline:
        paths = list(directory.glob("sessions/*/*/heartbeat.json"))
        if paths:
            active = json.loads(paths[0].read_text())
            if active.get("phase") == "measured":
                break
        assert identity_is_live(record["identity"]), record
        time.sleep(0.05)
    assert active and active["phase"] == "measured"
    requested = invoke(["stop", str(directory)], environment)
    assert requested.returncode == 0, requested.stderr
    assert json.loads(requested.stdout)["requested"]
    while time.monotonic() < deadline:
        status = experiment_status(directory)
        if status["status"] != "running":
            break
        time.sleep(0.05)
    assert status["status"] == "stopped"
    assert 1 <= status["counts"]["started"] < 6
    original_records = {path: path.read_bytes() for path in directory.glob("sessions/*/*/runs/*/*/run-record.json")}
    stop_path = next(directory.glob("segments/*/stop-request.json"))
    stopped_bytes = stop_path.read_bytes()
    # Let the same verified handle exit and release the inherited device lock.
    while identity_is_live(record["identity"]) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not identity_is_live(record["identity"])
    resumed = invoke(["resume", str(directory)], environment)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    state = json.loads((directory / "experiment-state.json").read_text())
    assert state["status"] == "complete"
    assert state["attempt_counts"]["scheduled"] == state["attempt_counts"]["started"] == 6
    assert state["attempt_counts"]["scientifically_valid"] == 6
    assert all(path.read_bytes() == original for path, original in original_records.items())
    assert stop_path.read_bytes() == stopped_bytes
    assert len(state["segments"]) == 2
    assert len(list(directory.glob("sessions/*/*/workers/*/protocol.jsonl.gz"))) == 2
    from pcsuchai.operation_costs import report_operation_costs
    cost_result = report_operation_costs([directory.parent / "operation-costs"], tmp_path / "master-cost-audit")
    assert cost_result["counts"] == {"returned": 3, "raised": 0, "unfinished": 0, "invalid": 0}
    saved_costs = json.loads(Path(cost_result["report_path"]).read_text())
    assert sorted(call["outcome"] for call in saved_costs["calls"]) == ["complete", "detached_handoff", "stopped"]
