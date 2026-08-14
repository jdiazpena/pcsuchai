from pathlib import Path

from pcsuchai.data import TRUSTED_COLUMNS, audit_measurements, load_measurements


ROOT = Path(__file__).parents[1]


def test_loads_only_trusted_source_products() -> None:
    measurements = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")

    assert len(measurements) == 26_725
    assert measurements.times[0].isoformat() == "2018-04-16T10:25:56+00:00"
    assert measurements.times[-1].isoformat() == "2018-09-27T04:54:29+00:00"
    assert measurements.particle_counts[0] == 66
    assert measurements.plasma_temperature[0] == 295.69375
    assert "Lon" not in TRUSTED_COLUMNS
    assert "Lat" not in TRUSTED_COLUMNS


def test_duplicate_times_are_preserved() -> None:
    measurements = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")
    duplicate_count = len(measurements.times) - len(set(measurements.times))
    assert duplicate_count == 255


def test_measurement_audit_counts_preserved_nonfinite_instrument_values() -> None:
    measurements = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")
    result = audit_measurements(measurements)
    assert result["status"] == "pass"
    assert result["duplicate_timestamps"] == 255
    assert result["fields"]["plasma_current"]["positive_infinity"] == 126
    assert result["fields"]["electron_density_300k"]["positive_infinity"] == 172
