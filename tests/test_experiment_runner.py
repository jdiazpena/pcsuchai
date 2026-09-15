import json
import os
from pathlib import Path

import pytest

import pcsuchai.benchmark_suite as suite
from pcsuchai.experiment import ExperimentManifest
from pcsuchai.experiment_control import identity_is_live, numerical_controls, process_identity, session_attempt_counts, experiment_status
from pcsuchai.experiment_runner import experiment_blocks, run_experiment


ROOT = Path(__file__).resolve().parents[1]


def manifest(**overrides):
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    data["sessions"] = 2
    data["workload"]["pairs"] = ["skyfield-apexpy"]
    data["retention"]["minimum_free_bytes"] = 0
    data.update(overrides)
    return ExperimentManifest.from_dict(data)


def fake_suite(output_dir, *args, **options):
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=options["resume"])
    count = options["repeats"] * len(options["scenario_pairs"])
    result = {"status": "complete", "report_path": str(path / "benchmark-session.json"),
              "attempt_counts": {"scheduled": count, "started": count, "scientifically_valid": count,
                                 "failed": 0, "interrupted": 0, "skipped": 0}}
    (path / "benchmark-session.json").write_text(json.dumps(result))
    (path / "benchmark-session.checkpoint.json").write_text(json.dumps(result))
    return result


def test_schedule_keeps_sessions_pairs_profiles_and_stop_semantics():
    for name in ("equal-work", "sustained", "persistent", "counters", "scaling", "overhead"):
        model = ExperimentManifest.load(ROOT / f"configs/experiments/{name}.json")
        blocks = experiment_blocks(model)
        assert {block["session_index"] for block in blocks} == set(range(1, model.data["sessions"] + 1))
        assert len({block["path"] for block in blocks}) == len(blocks)
        if name in ("sustained", "persistent", "counters"):
            assert all(len(block["pairs"]) == 1 for block in blocks)
        if name == "overhead":
            for session in range(1, 4):
                assert {block["observation_level"] for block in blocks if block["session_index"] == session} == {"minimal", "normal", "detailed"}
        if name == "scaling":
            assert {block["size"] for block in blocks} == {100, 1000, 10000, None}


def test_manifest_runner_commits_exact_work_and_restores_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "device.lock"))
    monkeypatch.setattr(suite, "run_benchmark_suite", fake_suite)
    original = dict(os.environ)
    result = run_experiment(manifest(), tmp_path / "experiment", ROOT, "local-test")
    assert result["status"] == "complete"
    assert result["attempt_counts"]["scheduled"] == result["attempt_counts"]["started"] == 2
    state = json.loads((tmp_path / "experiment/experiment-state.json").read_text())
    assert len(state["blocks"]) == 2
    assert all(block["status"] == "complete" for block in state["blocks"])
    assert os.environ == original
    with pytest.raises(ValueError, match="completed"):
        run_experiment(manifest(), tmp_path / "experiment", ROOT, "local-test", resume=True)


def test_stop_and_resume_do_not_repeat_finished_blocks_or_delete_request(tmp_path, monkeypatch):
    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "device.lock"))
    calls = []

    def stop_after_first(path, *args, **options):
        calls.append(str(path))
        result = fake_suite(path, *args, **options)
        root = tmp_path / "experiment"
        state = json.loads((root / "experiment-state.json").read_text())
        request = root / "segments" / state["segments"][-1]["id"] / "stop-request.json"
        request.write_text('{"policy":"finish_active_job_then_stop"}')
        return result

    monkeypatch.setattr(suite, "run_benchmark_suite", stop_after_first)
    first = run_experiment(manifest(), tmp_path / "experiment", ROOT, "local-test")
    assert first["status"] == "stopped"
    assert first["attempt_counts"]["started"] == 1
    request = next((tmp_path / "experiment/segments").glob("*/stop-request.json"))
    before = request.read_bytes()
    monkeypatch.setattr(suite, "run_benchmark_suite", fake_suite)
    final = run_experiment(manifest(), tmp_path / "experiment", ROOT, "local-test", resume=True)
    assert final["status"] == "complete"
    assert final["attempt_counts"]["started"] == 2
    assert request.read_bytes() == before
    assert len(json.loads((tmp_path / "experiment/experiment-state.json").read_text())["segments"]) == 2


def test_process_identity_rejects_stale_reused_pid():
    identity = process_identity()
    assert identity_is_live(identity)
    assert not identity_is_live({**identity, "start_clock_ticks": identity["start_clock_ticks"] + 1})
    assert not identity_is_live({**identity, "boot_id": "another-boot"})


def test_affinity_outside_allowed_mask_does_not_modify_environment():
    original = dict(os.environ)
    with pytest.raises(ValueError, match="allowed CPU"):
        with numerical_controls("one", [max(os.sched_getaffinity(0)) + 1]):
            pytest.fail("invalid affinity accepted")
    assert dict(os.environ) == original


def test_counts_include_failed_slots_without_waiting_for_final_report():
    state = {"settings": {"repeats": 3, "duration_seconds": None}, "scenarios": {"skyfield-apexpy": {}},
             "execution_order": [{"kind": "warmup", "round": 1, "scenario": "skyfield-apexpy", "status": "complete"},
                                 {"kind": "measured", "round": 1, "scenario": "skyfield-apexpy", "status": "failed"}]}
    counts = session_attempt_counts(state)
    assert counts["started"] == counts["failed"] == 1
    assert counts["scientifically_valid"] == 0 and counts["skipped"] == 2
    state["execution_order"].append(dict(state["execution_order"][-1]))
    with pytest.raises(ValueError, match="duplicate"):
        session_attempt_counts(state)


def test_live_status_reads_committed_block_counts(tmp_path):
    state = {"manifest": manifest().data, "status": "running", "segments": [{"identity": process_identity()}],
             "blocks": [{"path": "sessions/first", "pairs": ["skyfield-apexpy"], "status": "running"}]}
    block = tmp_path / "sessions/first"
    block.mkdir(parents=True)
    (block / "benchmark-session.checkpoint.json").write_text(json.dumps({
        "settings": {"repeats": 1}, "scenarios": {"skyfield-apexpy": {}},
        "execution_order": [{"kind": "measured", "round": 1, "scenario": "skyfield-apexpy", "status": "complete"}]}))
    (tmp_path / "experiment-state.json").write_text(json.dumps(state))
    assert experiment_status(tmp_path)["counts"]["scientifically_valid"] == 1


def test_thread_controls_record_effective_values_even_if_unchanged(monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    with numerical_controls("one", None) as controls:
        assert controls["thread_environment"]["OPENBLAS_NUM_THREADS"] == "1"


@pytest.mark.parametrize("accepted", [True, False])
def test_saved_workload_acceptance_follows_jobs_and_can_reject_root_completion(tmp_path, monkeypatch, accepted):
    """Synthetic orchestration evidence only; native fidelity has its own tests."""

    import pcsuchai.full_validation as validation
    import pcsuchai.validation_reference as reference

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "device.lock"))
    order = []

    def jobs(*args, **options):
        order.append("jobs")
        return fake_suite(*args, **options)

    def golden(output, *args, **options):
        order.append("full-validation")
        path = Path(output) / "fake-certificate.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        return {"certificate_path": str(path), "status": "pass", "official_eligible": True}

    def audit(experiment, output):
        order.append("saved-workload-acceptance")
        assert experiment["state"]["phase"] == "postmeasurement_workload_acceptance"
        assert all(block["status"] == "complete" for block in experiment["state"]["blocks"])
        assert experiment["state"]["full_validation_certificate"]
        Path(output).mkdir(parents=True)
        result = {"status": "accepted" if accepted else "incomplete_or_failed", "attempt_counts": {},
                  "wall_seconds": 12.0, "process_cpu_seconds": 2.0}
        (Path(output) / "workload-acceptance.json").write_text(json.dumps(result))
        return result

    monkeypatch.setattr(suite, "run_benchmark_suite", jobs)
    monkeypatch.setattr(validation, "run_full_validation", golden)
    monkeypatch.setattr(reference, "audit_experiment_workloads", audit)
    data = manifest().data
    data["sessions"] = 1
    data["workload"]["pairs"] = ["astropy-aacgmv2", "astropy-apexpy", "skyfield-aacgmv2", "skyfield-apexpy"]
    result = run_experiment(ExperimentManifest.from_dict(data), tmp_path / "experiment", ROOT, "local-mocked-orchestration")
    assert order == ["jobs", "full-validation", "saved-workload-acceptance"]
    state = json.loads((tmp_path / "experiment/experiment-state.json").read_text())
    assert state["workload_acceptance"]["wall_seconds"] == 12.0
    assert result["status"] == ("complete" if accepted else "stopped")
    if not accepted:
        assert "full-reference scientific acceptance" in result["reason"]
        assert state["scientific_classification"] == "scientifically_incomplete_or_failed"
