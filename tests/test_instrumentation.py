import csv
import gzip
import json
import os
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.pipeline import run_analysis
from pcsuchai.benchmark_suite import _validate_run
from pcsuchai.worker import PersistentWorker, request_from_analysis_command


ROOT = Path(__file__).resolve().parents[1]


def options(directory, level):
    return dict(measurement_path=str(ROOT / "data/raw/langmuir-2018-2.csv"),
                tle_path=str(ROOT / "data/tle/suchai1.tle"), eop_path=str(ROOT / "data/eop/finals2000A.all"),
                output_dir=str(directory), orbit_backend="skyfield", magnetic_backend="apexpy",
                limit=20, selection_method="spread", plot_config_path=None, benchmark=True,
                observation_level=level, stage_interval_seconds=0.02, native_memory_interval_seconds=0.5)


def test_levels_keep_identical_science_and_all_acquired_raw_samples(tmp_path):
    baseline = None
    for level in ("minimal", "normal", "detailed"):
        result = run_analysis(**options(tmp_path / level, level))
        _validate_run(result.__dict__, 1)
        with np.load(result.raw_products_npz, allow_pickle=False) as raw:
            actual = {name: raw[name] for name in raw.files}
        if baseline is not None:
            for name, expected in baseline.items():
                assert np.array_equal(actual[name], expected, equal_nan=True) if expected.dtype.kind in "fc" else np.array_equal(actual[name], expected)
        baseline = actual
        stages = json.loads(Path(result.benchmark_json).read_text())
        if level == "minimal":
            assert not stages
            assert result.raw_benchmark_samples is None
        else:
            assert stages
            with gzip.open(result.raw_benchmark_samples, "rt") as stream:
                samples = list(csv.DictReader(stream))
            assert samples
            assert all(float(row["sample_interval_seconds"]) == 0.02 for row in samples)
            if level == "detailed":
                assert any(json.loads(row["process_details_json"]).get("threads", {}).get("status") == "available" for row in samples)
            else:
                assert not any(row["process_details_json"] for row in samples)


def test_worker_translation_keeps_observation_controls(tmp_path):
    command = ["python", "-m", "pcsuchai", "analyze", "--measurements", "data.csv", "--tle", "tle",
               "--eop", "eop", "--output-dir", str(tmp_path / "products"), "--orbit-backend", "skyfield",
               "--magnetic-backend", "apexpy", "--benchmark", "--observation-level", "detailed",
               "--stage-interval-seconds", "0.2", "--native-memory-interval-seconds", "5"]
    request = request_from_analysis_command(command, "attempt")
    assert request["observation_level"] == "detailed"
    assert request["stage_interval_seconds"] == 0.2
    assert request["native_memory_interval_seconds"] == 5


def test_persistent_minimal_mode_keeps_same_pipeline_contract(tmp_path):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    with PersistentWorker(tmp_path / "worker", environment) as worker:
        result, elapsed, response = worker.execute({"request_id": "attempt", **options(tmp_path / "attempt/products", "minimal")})
        assert response["status"] == "complete"
        assert result["raw_benchmark_samples"] is None
        assert not _validate_run(result, elapsed)["stages"]


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_invalid_cadence_cannot_start_measurement(tmp_path, value):
    with pytest.raises(ValueError, match="finite and positive"):
        run_analysis(**{**options(tmp_path, "normal"), "stage_interval_seconds": value})
