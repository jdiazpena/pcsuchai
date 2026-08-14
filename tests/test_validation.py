import csv
import json
from pathlib import Path

import numpy as np

from pcsuchai.models import OrbitResult
from pcsuchai.validation import (
    compare_orbits,
    validate_magnetic_backends,
    validate_orbit_backends,
)


ROOT = Path(__file__).parents[1]


def test_longitude_comparison_wraps_dateline() -> None:
    first = OrbitResult(np.array([1.0]), np.array([179.9]), np.array([500.0]), np.array([0]), "a")
    second = OrbitResult(np.array([1.1]), np.array([-179.9]), np.array([500.1]), np.array([0]), "b")
    result = compare_orbits(first, second)
    assert np.isclose(result["longitude_difference_deg"]["max"], 0.2)
    assert result["positions_total"] == 1
    assert result["first_valid_positions"] == 1
    assert result["position_3d_separation_km"]["max"] > 0


def test_orbit_comparison_reports_unmatched_validity() -> None:
    first = OrbitResult(
        np.array([1.0, np.nan]), np.array([2.0, np.nan]), np.array([500.0, np.nan]),
        np.array([0, 6]), "astropy",
    )
    second = OrbitResult(
        np.array([1.0, 3.0]), np.array([2.0, 4.0]), np.array([500.0, 501.0]),
        np.array([0, 0]), "skyfield",
    )
    result = compare_orbits(first, second)
    assert result["second_only_valid_positions"] == 1
    assert result["first_error_codes"] == {"0": 1, "6": 1}
    assert result["consistency_status"] == "fail"


def test_orbit_validator_writes_parity_artifacts(tmp_path: Path) -> None:
    validation = tmp_path / "orbit-validation.json"
    benchmark = tmp_path / "orbit-benchmark.json"
    differences = tmp_path / "orbit-differences.csv"
    result = validate_orbit_backends(
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        ROOT / "data/eop/finals2000A.all",
        validation, limit=5, benchmark_output_path=benchmark,
        differences_output_path=differences,
    )
    assert result["consistency_status"] == "pass"
    assert validation.is_file() and benchmark.is_file() and differences.is_file()
    stages = json.loads(benchmark.read_text())
    assert [item["stage"] for item in stages] == [
        "propagate_orbit_astropy", "propagate_orbit_skyfield"
    ]
    with differences.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    assert rows[0]["tle_epoch_utc"]


def test_magnetic_validator_uses_same_artifact_contract(tmp_path: Path) -> None:
    validation = tmp_path / "magnetic-validation.json"
    benchmark = tmp_path / "magnetic-benchmark.json"
    differences = tmp_path / "magnetic-differences.csv"
    result = validate_magnetic_backends(
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        ROOT / "data/eop/finals2000A.all",
        "astropy", validation, benchmark, limit=5,
        differences_output_path=differences,
    )
    assert result["execution_status"] == "pass"
    assert validation.is_file() and benchmark.is_file() and differences.is_file()
    stages = json.loads(benchmark.read_text())
    assert [item["stage"] for item in stages] == [
        "convert_magnetic_aacgmv2", "convert_magnetic_apexpy"
    ]
    with differences.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 5
    assert rows[0]["orbit_latitude_deg"]
