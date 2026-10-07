"""Real local science plus policy-aware completion, retention and reporting."""

import copy
import gzip
import json
import os
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np
import pytest

import pcsuchai.pipeline as pipeline
from pcsuchai.benchmark_suite import _validate_run, _check_repeat_consistency
from pcsuchai.experiment import ExperimentManifest
from pcsuchai.experiment_runner import experiment_blocks, run_experiment
from pcsuchai.experiment_report import report_experiments
from pcsuchai.onboard_validation import validate_onboard_manifest
from pcsuchai.output_policy import effective_output_policy, policy_origin
from pcsuchai.portable import export_experiment, import_experiment, verify_import
from pcsuchai.saved_attempts import saved_experiment, iter_saved_attempts


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("orbit,magnetic", [("astropy", "aacgmv2"), ("astropy", "apexpy"),
                                           ("skyfield", "aacgmv2"), ("skyfield", "apexpy")])
def test_policies_execute_equal_native_science_and_all_recipes(tmp_path, monkeypatch, orbit, magnetic):
    """Compare actual arrays before saving; counts alone would not prove parity."""

    captured = {}
    active = None
    for name in ("propagate", "convert_magnetic", "select_plot_data"):
        original = getattr(pipeline, name)

        def observe(*args, _original=original, _name=name, **kwargs):
            result = _original(*args, **kwargs)
            captured[active].setdefault(_name, []).append(copy.deepcopy(result))
            return result

        monkeypatch.setattr(pipeline, name, observe)
    outputs = {}
    for policy in ("validation", "onboard"):
        active = policy
        captured[policy] = {}
        outputs[policy] = pipeline.run_analysis(
            ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle", tmp_path / policy,
            eop_path=ROOT / "data/eop/finals2000A.all", orbit_backend=orbit, magnetic_backend=magnetic,
            plot_config_path=ROOT / "configs/plots/archive-full.json", limit=40,
            selection_method="spread", benchmark=True, output_policy=policy,
        )
    assert len(captured["onboard"]["select_plot_data"]) == 32
    for name in captured["validation"]:
        for first, second in zip(captured["validation"][name], captured["onboard"][name], strict=True):
            for field in fields(first):
                np.testing.assert_array_equal(getattr(first, field.name), getattr(second, field.name))
    onboard = outputs["onboard"]
    assert onboard.positions_csv is onboard.magnetic_positions_csv is onboard.raw_products_npz is None
    assert onboard.plot_selection_files == () and len(onboard.configured_plot_files) == 32
    assert not list((tmp_path / "onboard").glob("*.npz"))
    assert not list((tmp_path / "onboard").glob("*.csv"))
    first = json.loads(Path(outputs["validation"].manifest_json).read_text())
    second = json.loads(Path(onboard.manifest_json).read_text())
    assert "source_rows" not in second["workload_selection"]
    assert [item["points_rendered"] for item in first["configured_plots"]] == [item["points_rendered"] for item in second["configured_plots"]]
    assert _validate_run(asdict(onboard), 1.0)["image_validation"]["passed"]
    for a, b in zip(outputs["validation"].configured_plot_files, onboard.configured_plot_files, strict=True):
        assert Path(a).read_bytes() == Path(b).read_bytes()
    for key in ("particle_map_png", "magnetic_particle_map_png", "footpoint_particle_map_png"):
        assert Path(getattr(outputs["validation"], key)).read_bytes() == Path(getattr(onboard, key)).read_bytes()
    assert Path(onboard.raw_benchmark_samples).is_file()
    with gzip.open(onboard.raw_benchmark_samples, "rt") as stream:
        assert len(stream.readlines()) > 1
    assert sum(p.stat().st_size for p in (tmp_path / "onboard").rglob("*") if p.is_file()) < sum(
        p.stat().st_size for p in (tmp_path / "validation").rglob("*") if p.is_file())
    damaged = copy.deepcopy(second)
    damaged["configured_plots"][0]["selected_count"] += 1
    assert not validate_onboard_manifest(damaged)["passed"]
    damaged = copy.deepcopy(second)
    damaged["orbit_integrity"]["error_counts"]["0"] -= 1
    assert not validate_onboard_manifest(damaged)["passed"]
    damaged = copy.deepcopy(second)
    damaged["magnetic_integrity"]["checks"]["mlt_range_hours"] = False
    assert not validate_onboard_manifest(damaged)["passed"]
    damaged = copy.deepcopy(second)
    damaged["completed_stages"].remove("propagate_orbit")
    assert not validate_onboard_manifest(damaged)["passed"]
    damaged = copy.deepcopy(second)
    damaged["settings"]["output_policy"] = "validation"
    assert not validate_onboard_manifest(damaged)["passed"]
    damaged = copy.deepcopy(second)
    damaged["invalid_magnetic_positions"] += 1
    assert not validate_onboard_manifest(damaged)["passed"]
    original_image = Path(onboard.configured_plot_files[0]).read_bytes()
    Path(onboard.configured_plot_files[0]).write_bytes(b"invalid png")
    assert not validate_onboard_manifest(second)["passed"]
    Path(onboard.configured_plot_files[0]).write_bytes(original_image)


def test_policy_contract_keeps_historical_hashes_and_paths():
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    data["workload"].pop("output_policy")
    legacy = ExperimentManifest.from_dict(data)
    paths = [item["path"] for item in experiment_blocks(legacy)]
    assert "output_policy" not in legacy.data["workload"]
    assert effective_output_policy(legacy.data["workload"]) == "validation"
    assert policy_origin(legacy.data["workload"]) == "historical_implicit_validation"
    data["workload"]["output_policy"] = "onboard"
    new = ExperimentManifest.from_dict(data)
    assert new.sha256 != legacy.sha256
    assert paths != [item["path"] for item in experiment_blocks(new)]
    data["workload"]["output_policy"] = "typo"
    with pytest.raises(ValueError, match="output_policy"):
        ExperimentManifest.from_dict(data)
    assert not _check_repeat_consistency([{"output_policy": "onboard"}, {"output_policy": "validation"}])["all_consistent"]


def test_cli_reports_onboard_completion_without_claiming_numeric_equality(tmp_path, monkeypatch, capsys):
    """Mock only orchestration; prove CLI policy/default/exit/labels explicitly."""

    import pcsuchai.benchmark_suite as suite
    from pcsuchai.cli import main

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "cli.lock"))
    received = {}

    def completed(**settings):
        received.update(settings)
        return {"status": "complete", "report_path": "report.json", "scenarios": {},
                "scientific_outputs_consistent": None, "output_summaries_consistent": True}

    monkeypatch.setattr(suite, "run_benchmark_suite", completed)
    assert main(["benchmark-suite", "--output-dir", str(tmp_path / "output")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert received["output_policy"] == result["output_policy"] == "onboard"
    assert result["scientific_outputs_consistent"] is None and result["output_summaries_consistent"] is True


def test_onboard_failure_is_explicit_and_never_overwritten(tmp_path):
    options = {"output_dir": tmp_path / "products", "output_policy": "onboard"}
    with pytest.raises(Exception):
        pipeline.run_analysis(tmp_path / "missing.csv", ROOT / "data/tle/suchai1.tle", **options)
    manifest = tmp_path / "products/manifest-astropy.json"
    before = manifest.read_bytes()
    record = json.loads(before)
    assert record["status"] == "failed" and record["output_policy"] == "onboard"
    assert record["error"]["type"] and record["partial_products_retained"]
    with pytest.raises(FileExistsError):
        pipeline.run_analysis(tmp_path / "missing.csv", ROOT / "data/tle/suchai1.tle", **options)
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("level", ["minimal", "normal", "detailed"])
def test_onboard_observation_levels_keep_completion_and_acquired_samples(tmp_path, level):
    """Completion recording is independent of whether stage timings are acquired."""

    outputs = pipeline.run_analysis(ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle",
                                    tmp_path / level, eop_path=ROOT / "data/eop/finals2000A.all",
                                    orbit_backend="skyfield", magnetic_backend="apexpy", limit=8,
                                    benchmark=True, observation_level=level, output_policy="onboard")
    checked = _validate_run(asdict(outputs), 1.0)
    assert checked["image_validation"]["passed"]
    manifest = json.loads(Path(outputs.manifest_json).read_text())
    assert len(manifest["completed_stages"]) == 7
    if level == "minimal":
        assert checked["stages"] == [] and outputs.raw_benchmark_samples is None
    else:
        assert checked["stages"] and Path(outputs.raw_benchmark_samples).is_file()


@pytest.mark.parametrize("process_mode", ["fresh", "persistent"])
def test_onboard_repeated_jobs_retention_import_and_report(tmp_path, monkeypatch, process_mode):
    """Actual local workers; a short uncontrolled protocol, not Pi performance."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "device.lock"))
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    data["name"] = "local-onboard"
    data["kind"] = "persistent" if process_mode == "persistent" else "acceptance"
    data["workload"]["output_policy"] = "onboard"
    data["workload"]["pairs"] = ["skyfield-apexpy"]
    data["workload"]["selection"]["sizes"] = [12]
    data["execution"]["process_mode"] = process_mode
    data["execution"]["ordering"] = "scenario_blocks" if process_mode == "persistent" else "balanced"
    data["execution"]["stop"]["value"] = 2
    data["execution"]["warmups"] = 1
    data["observation"]["board_interval_seconds"] = 0.2
    data["retention"]["minimum_free_bytes"] = 0
    model = ExperimentManifest.from_dict(data)
    protocol = tmp_path / "protocol.json"
    protocol.write_text(model.canonical_json)
    launched = subprocess.run([sys.executable, str(ROOT / "scripts/run_experiment.py"), "run", "--manifest", str(protocol),
                               "--device-label", "local-policy-test", "--output-root", str(tmp_path / "experiments")],
                              cwd=ROOT, capture_output=True, text=True, timeout=120, env=dict(os.environ))
    assert launched.returncode == 0, launched.stdout + launched.stderr
    experiment = next((tmp_path / "experiments").glob("local-policy-test/*/*/*/*"))
    state = json.loads((experiment / "experiment-state.json").read_text())
    assert state["status"] == "complete" and state["attempt_counts"]["started"] == 2
    attempts = list(iter_saved_attempts(saved_experiment(experiment)))
    assert len(attempts) == 3 and all(item["status"] == "complete" and not item["issues"] for item in attempts)
    assert all(item["products"]["raw_products"] is None for item in attempts)
    assert all(item["output_policy"] == "onboard" for item in attempts)
    assert len(list(experiment.rglob("*.samples.csv.gz"))) >= 3
    assert len(list(experiment.rglob("system-telemetry.csv.gz"))) >= 3
    bundle = export_experiment(experiment, tmp_path / "bundle.tar.gz")
    imported = import_experiment(tmp_path / "bundle.tar.gz", tmp_path / "imported", expected_sha256=bundle["sha256"])
    assert imported["passed"] and verify_import(tmp_path / "imported", verify_images=True)["passed"]
    report = report_experiments([tmp_path / "imported"], tmp_path / "report", resamples=100)
    assert report["status"] == "diagnostic_report_created"
    assert report["attempt_counts"]["product_valid"] == 2
    saved = json.loads(Path(report["report_path"]).read_text())
    assert saved["cohorts"][0]["controlled_settings"]["output_policy"] == "onboard"
    assert all(item["status"] == "unavailable" and item["passed"] is None for item in saved["numerical_comparisons"])
