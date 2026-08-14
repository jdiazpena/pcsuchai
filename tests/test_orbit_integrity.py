from pathlib import Path

from pcsuchai.data import load_measurements
from pcsuchai.orbit.integrity import (
    audit_eop_coverage,
    skyfield_time_data_provenance,
    validate_sgp4_reference_vector,
)


ROOT = Path(__file__).parents[1]


def test_eop_table_covers_every_measurement() -> None:
    measurements = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")
    result = audit_eop_coverage(ROOT / "data/eop/finals2000A.all", measurements.times)
    assert result["status"] == "pass"
    assert result["finite_interpolations"] == len(measurements)
    assert result["automatic_downloads_enabled"] is False


def test_sgp4_reference_vector_passes() -> None:
    result = validate_sgp4_reference_vector()
    assert result["status"] == "pass"


def test_skyfield_offline_time_files_are_hashed() -> None:
    result = skyfield_time_data_provenance()
    assert set(result["files"]) == {"iers.npz", "delta_t.npz", "nutation.npz"}
    assert all(len(item["sha256"]) == 64 for item in result["files"].values())
