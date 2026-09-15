"""Native science/image products; synthetic scheduling/timing fault fixtures."""

import gzip
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from pcsuchai.benchmark import runtime_metadata, sha256_file
from pcsuchai.benchmark_suite import _source_digest, _validate_run
from pcsuchai.experiment import ExperimentManifest
from pcsuchai.experiment_runner import experiment_blocks
from pcsuchai.experiment_report import ReadingTrend, report_experiments
from pcsuchai.pipeline import run_analysis
from pcsuchai.saved_attempts import iter_saved_attempts, saved_experiment
from pcsuchai.retention import snapshot_inputs, snapshot_sources
from pcsuchai.experiment_runner import safe_name
import hashlib


ROOT = Path(__file__).resolve().parents[1]


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, allow_nan=False))


@pytest.fixture
def saved_native_experiment(tmp_path):
    # Actual native science/images; synthetic attempts/timers are NOT performance
    # evidence. A second fixture can model another independently named session.
    root = tmp_path / "native-saved"
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    data["workload"]["pairs"] = ["skyfield-apexpy"]
    data["workload"]["selection"]["sizes"] = [6]
    data["execution"]["stop"]["value"] = 2
    manifest = ExperimentManifest.from_dict(data)
    blocks = experiment_blocks(manifest)
    block = root / blocks[0]["path"]
    run = block / "runs/2026-09-15/20260915T000000Z-r000001-skyfield-apexpy"
    outputs = run_analysis(ROOT / data["workload"]["measurements"], ROOT / data["workload"]["tle"],
                           run / "products", orbit_backend="skyfield", magnetic_backend="apexpy",
                           eop_path=ROOT / data["workload"]["eop"], limit=6, benchmark=True)
    record = _validate_run(asdict(outputs), 1.0)
    record.update(run_id=run.name, repeat=1, status="complete", command=["--orbit-backend", "skyfield", "--magnetic-backend", "apexpy"],
                  started_utc="2026-09-15T00:00:00+00:00", run_directory=str(run),
                  process_execution={"external_timer_scope": "process_launch_to_exit"})
    write(run / "run-record.json", record)
    write(run / "cycle-timing.json", {"schema_version": 2, "run_id": run.name, "full_cycle_seconds": 1.5})
    state = {"manifest": data, "manifest_sha256": manifest.sha256, "runtime": runtime_metadata(),
             "source": _source_digest(ROOT), "device_label": "synthetic-metadata-local", "started_utc": "2026-09-15T00:00:00+00:00",
             "segments": [], "blocks": blocks, "status": "stopped",
             "inputs": {key: {"sha256": sha256_file(ROOT / data["workload"][key]), "size_bytes": (ROOT / data["workload"][key]).stat().st_size}
                        for key in ("measurements", "tle", "eop")}}
    state["input_snapshots"] = snapshot_inputs({f"{safe_name(key)}-{hashlib.sha256(key.encode()).hexdigest()[:8]}": ROOT / data["workload"][key]
                                               for key in ("measurements", "tle", "eop")}, root / "inputs")
    state["source_snapshot"] = snapshot_sources(ROOT, state["source"], root / "source-snapshot.tar.gz")
    write(root / "manifest.json", data)
    write(root / "experiment-state.json", state)
    return root, block, run, record


def test_reader_rechecks_native_products_and_uncommitted_time(saved_native_experiment):
    root, _block, run, _record = saved_native_experiment
    item = list(iter_saved_attempts(saved_experiment(root)))[0]
    assert item["status"] == "complete"
    assert item["products"]["raw_audit"]["passed"]
    assert item["products"]["images"]["passed"]
    assert not item["checkpoint_indexed"]
    assert item["full_cycle_seconds"] == 1.5
    (run / "cycle-timing.json").unlink()  # only this test-owned artifact
    item = list(iter_saved_attempts(saved_experiment(root)))[0]
    assert item["full_cycle_seconds"] is None
    assert item["cycle_timing_status"] == "unavailable_uncommitted"


def test_scaling_descriptor_measures_bound_png_bytes_not_metadata(saved_native_experiment):
    root, _block, run, record = saved_native_experiment
    manifest_path = Path(record["artifacts"]["manifest_json"]["path"])
    manifest = json.loads(manifest_path.read_text())
    manifest["plot"]["size_bytes"] = 0  # Incorrect test-owned size metadata.
    write(manifest_path, manifest)
    record["artifacts"]["manifest_json"].update(sha256=sha256_file(manifest_path), size_bytes=manifest_path.stat().st_size)
    write(run / "run-record.json", record)
    item = list(iter_saved_attempts(saved_experiment(root)))[0]
    assert item["products"]["passed"]
    plots = item["products"]["workload_details"]["plot_products"]
    assert plots[0]["size_bytes"] == Path(manifest["plot"]["path"]).stat().st_size > 0
    assert plots[0]["metadata_size_bytes"] == 0
    assert plots[0]["metadata_size_matches_file"] is False
    assert plots[0]["size_source"] == "stat of bound/hash-verified readable PNG"


def test_partial_and_torn_slots_remain_in_denominator(saved_native_experiment, tmp_path):
    root, block, _run, _record = saved_native_experiment
    partial = block / "runs/2026-09-15/20260915T000001Z-r000002-skyfield-apexpy"
    partial.mkdir()
    result = report_experiments([root], tmp_path / "report", resamples=100)
    assert result["status"] == "partial_or_excluded"
    assert result["attempt_counts"]["started"] == 2
    assert result["attempt_counts"]["interrupted"] == 1
    report = json.loads(Path(result["report_path"]).read_text())
    assert report["experiments"][0]["counts"]["skipped"] == 0
    assert report["cohorts"][0]["worker_latency"]["attempt_count"] == 1
    assert len(report["cohorts"]) == 1  # Outcomes must not split controlled work.
    assert report["cohorts"][0]["counts"]["started"] == 2
    assert report["cohorts"][0]["counts"]["interrupted"] == 1
    assert report["cohorts"][0]["worker_latency"]["uncertainty"]["status"] == "unavailable"
    (partial / "run-record.json").write_text('{"broken":')
    items = list(iter_saved_attempts(saved_experiment(root)))
    assert items[1]["status"] == "failed"
    assert items[1]["issues"]
    assert (partial / "run-record.json").read_text() == '{"broken":'


def test_missing_checkpoint_attempt_is_failed_not_skipped(saved_native_experiment):
    root, block, _run, _record = saved_native_experiment
    write(block / "benchmark-session.checkpoint.json", {"execution_order": [{"run_id": "missing-r000002-skyfield-apexpy",
                                                                          "kind": "measured", "round": 2, "scenario": "skyfield-apexpy", "status": "complete"}]})
    items = list(iter_saved_attempts(saved_experiment(root)))
    assert len(items) == 2
    assert items[1]["status"] == "failed"
    assert items[1]["classification"] == "excluded_missing_retained_attempt"


def test_both_duplicate_slots_are_excluded(saved_native_experiment):
    root, block, _run, _record = saved_native_experiment
    (block / "runs/2026-09-15/20260915T000001Z-r000001-skyfield-apexpy").mkdir()
    items = list(iter_saved_attempts(saved_experiment(root)))
    assert len(items) == 2
    assert all(any("multiple retained" in issue for issue in item["issues"]) for item in items)


def test_artifact_tampering_does_not_enter_timing_average(saved_native_experiment):
    root, _block, _run, record = saved_native_experiment
    Path(record["artifacts"]["raw_products_npz"]["path"]).write_bytes(b"damaged test fixture")
    item = list(iter_saved_attempts(saved_experiment(root)))[0]
    assert item["status"] == "failed"
    assert "integrity failed" in item["issues"][0]


def test_duplicate_experiment_cannot_invent_independent_sessions(saved_native_experiment, tmp_path):
    root, *_rest = saved_native_experiment
    with pytest.raises(ValueError, match="double-count"):
        report_experiments([root, root], tmp_path / "report", resamples=100)
    assert not (tmp_path / "report").exists()


def test_launch_observation_variant_is_a_control_not_an_ignored_wrapper(saved_native_experiment):
    """Wrapped, unwrapped and detached handoff contexts cannot silently merge."""

    from copy import deepcopy
    from pcsuchai.saved_attempts import controlled_settings
    root, *_rest = saved_native_experiment
    experiment = saved_experiment(root)
    block = experiment["blocks"][0]
    plain = controlled_settings(experiment, block)
    wrapped = deepcopy(experiment)
    wrapped["state"]["runtime"]["launch_observation_declaration"] = '{"attachment_scope":"current_command_until_exit"}'
    detached = deepcopy(wrapped)
    detached["state"]["runtime"]["launch_observation_declaration"] = '{"attachment_scope":"upstream_detached_launcher_only_not_active_job_tee"}'
    assert plain != controlled_settings(wrapped, block) != controlled_settings(detached, block)


def test_torn_root_state_still_inventories_attempts(saved_native_experiment):
    root, *_rest = saved_native_experiment
    (root / "experiment-state.json").write_text("{torn")
    experiment = saved_experiment(root)
    assert experiment["issues"]
    item = list(iter_saved_attempts(experiment))[0]
    assert item["cohort_id"] is None
    assert item["products"]["passed"]


def test_two_blocks_same_board_keep_independent_session_identity(saved_native_experiment, tmp_path):
    root, block, run, record = saved_native_experiment
    data = json.loads((root / "manifest.json").read_text())
    data["sessions"] = 2
    manifest = ExperimentManifest.from_dict(data)
    write(root / "manifest.json", data)
    state = json.loads((root / "experiment-state.json").read_text())
    state.update(manifest=data, manifest_sha256=manifest.sha256, blocks=experiment_blocks(manifest))
    write(root / "experiment-state.json", state)
    second = root / state["blocks"][1]["path"] / "runs/2026-09-16/20260916T000000Z-r000001-skyfield-apexpy"
    # The synthetic job shares immutable native products; timings are fixtures.
    write(second / "run-record.json", {**record, "run_id": second.name})
    write(second / "cycle-timing.json", {"schema_version": 2, "run_id": second.name, "full_cycle_seconds": 1.5})
    before = {str(path): sha256_file(path) for path in root.rglob("*") if path.is_file()}
    result = report_experiments([root], tmp_path / "two-session-report", resamples=100)
    report = json.loads(Path(result["report_path"]).read_text())
    assert len(report["cohorts"]) == 1
    assert report["cohorts"][0]["worker_latency"]["session_count"] == 2
    assert report["numerical_comparisons"][0]["passed"]
    assert before == {str(path): sha256_file(path) for path in root.rglob("*") if path.is_file()}
    with gzip.open(Path(result["report_path"]).parent / "attempts.jsonl.gz", "rt") as stream:
        assert len(list(stream)) == 2


def test_streaming_trends_keep_zero_missing_and_regression_separate():
    trend = ReadingTrend()
    for value, instant, status in ((None, 0, "unsupported"), (0, 10, "available"), (2, 12, "available")):
        trend.add({"value": value, "monotonic_seconds": instant, "status": status})
    result = trend.report()
    assert result["numeric_sample_count"] == 2
    assert result["availability_counts"]["unsupported"] == 1
    assert result["minimum"] == 0
    assert result["linear_slope_per_second"] == 1
    trend.add({"value": 3, "monotonic_seconds": 11, "status": "available"})
    assert trend.report()["clock_regressions"] == 1
    assert trend.report()["linear_slope_per_second"] is None


def test_declared_minimal_cannot_use_normal_instrumentation(saved_native_experiment):
    from pcsuchai.saved_attempts import validate_saved_products
    root, _block, _run, record = saved_native_experiment
    experiment = saved_experiment(root)
    block = {**experiment["blocks"][0], "observation_level": "minimal"}
    result = validate_saved_products(record, experiment["paths"], expected_block=block)
    assert not result["passed"]
    assert not result["frozen_variant_checks"]["observation_level"]


def test_snapshot_tampering_excludes_controls_but_preserves_inventory(saved_native_experiment):
    root, *_rest = saved_native_experiment
    path = next((root / "inputs").glob("measurements-*.gz"))
    path.write_bytes(b"test-owned compressed corruption")
    experiment = saved_experiment(root)
    assert not experiment["provenance_available"]
    assert experiment["issues"]
    items = list(iter_saved_attempts(experiment))
    assert len(items) == 1
    assert items[0]["cohort_id"] is None


def test_matched_overhead_uses_session_pairs_not_an_assumed_cost(saved_native_experiment):
    from pcsuchai.saved_attempts import controlled_settings
    from pcsuchai.experiment_report import _overhead
    root, *_rest = saved_native_experiment
    experiment = saved_experiment(root)
    controls = controlled_settings(experiment, experiment["blocks"][0])
    controls["kind"] = "overhead"
    groups = {}
    for level, factor in (("minimal", 1), ("normal", 2)):
        settings = json.loads(json.dumps(controls))
        settings["observation"]["levels"] = [level]
        groups[(level, "test-board")] = [{"controls": settings, "device_label": "test-board", "pair": "skyfield-apexpy",
                                          "session_id": identity, "kind": "measured", "status": "complete", "issues": [],
                                          "worker_seconds": duration * factor, "full_cycle_seconds": duration * factor}
                                         for identity, duration in (("a", 1), ("b", 2))]
    reports = _overhead(groups, seed=7, resamples=100)
    assert len(reports) == 2
    assert all(report["overhead_percent"] == 100 for report in reports)
    assert all(report["overhead_percent_interval"] == [100, 100] for report in reports)
    assert not any(report["assumed_overhead_subtracted"] for report in reports)


def test_native_observation_envelope_schema_is_metadata_not_a_malformed_role(saved_native_experiment, tmp_path):
    import csv
    from pcsuchai.observations import ObservationSampler
    root, block, _run, _record = saved_native_experiment
    observations = ObservationSampler().capture(tmp_path)
    assert observations["schema_version"] == 1
    with (block / "system-telemetry.test.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("observations_json", "segment_id", "phase", "campaign_elapsed_seconds"))
        writer.writeheader()
        writer.writerow({"observations_json": json.dumps(observations), "segment_id": "native-test", "phase": "measured",
                         "campaign_elapsed_seconds": 0})
    result = report_experiments([root], tmp_path / "native-observation-report", resamples=100)
    report = json.loads(Path(result["report_path"]).read_text())
    assert result["status"] == "partial_or_excluded"  # fixture's stopped schedule stays partial
    assert report["observation_issues"] == []
    assert report["observation_rows"] == 1
    assert report["thermal_analysis"]["temperature_groups"][0]["status"] == "unavailable"
