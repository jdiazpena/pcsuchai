from datetime import datetime, timezone

import numpy as np

from pcsuchai.magnetic import convert_magnetic
from pcsuchai.models import OrbitResult
from pcsuchai.validation import compare_magnetic
from pcsuchai.magnetic.integrity import audit_magnetic_result


def test_both_magnetic_backends_return_valid_native_coordinates() -> None:
    times = (
        datetime(2018, 2, 1, 12, tzinfo=timezone.utc),
        datetime(2018, 8, 1, 12, tzinfo=timezone.utc),
    )
    orbit = OrbitResult(
        latitude_deg=np.array([-30.0, 45.0]),
        longitude_deg=np.array([-60.0, 20.0]),
        altitude_km=np.array([500.0, 510.0]),
        error_codes=np.zeros(2, dtype=np.int16),
        backend="test",
    )

    aacgm = convert_magnetic("aacgmv2", times, orbit)
    apex = convert_magnetic("apexpy", times, orbit)

    for result in (aacgm, apex):
        assert audit_magnetic_result(result, orbit)["passed"]
        assert np.all(result.error_codes == 0)
        assert np.all(np.isfinite(result.latitude_deg))
        assert np.all((-90 <= result.latitude_deg) & (result.latitude_deg <= 90))
        assert np.all((0 <= result.local_time_hours) & (result.local_time_hours < 24))
    comparison = compare_magnetic(aacgm, apex)
    assert comparison["positions_compared"] == 2
    assert "not accuracy errors" in comparison["interpretation"]
    assert np.all(np.isnan(aacgm.mapping_error_deg))
    assert np.all(np.isfinite(aacgm.surface_altitude_km))
    assert np.all(apex.surface_altitude_km == 0)
    assert np.all(np.isfinite(apex.mapping_error_deg))


def test_aacgm_undefined_equatorial_result_is_recorded() -> None:
    times = (datetime(2018, 4, 23, 23, 1, 43, tzinfo=timezone.utc),)
    orbit = OrbitResult(
        latitude_deg=np.array([4.6]), longitude_deg=np.array([-23.3]),
        altitude_km=np.array([504.2]), error_codes=np.zeros(1, dtype=np.int16),
        backend="test",
    )

    result = convert_magnetic("aacgmv2", times, orbit)

    assert result.error_codes.tolist() == [1]
    assert np.isnan(result.latitude_deg[0])
    assert np.isnan(result.surface_altitude_km[0])
    assert audit_magnetic_result(result, orbit)["passed"]


def test_aacgm_surface_altitude_matches_inverse_api_not_angular_error():
    import aacgmv2

    timestamp = datetime(2018, 5, 1, tzinfo=timezone.utc)
    orbit = OrbitResult(np.array([45.]), np.array([-77.]), np.array([500.]), np.array([0]), "test")
    result = convert_magnetic("aacgmv2", (timestamp,), orbit)
    expected = aacgmv2.convert_latlon(
        result.latitude_deg[0], result.longitude_deg[0], 0, timestamp,
        method_code="A2G|ALLOWTRACE",
    )
    assert result.surface_altitude_km[0] == expected[2]
    assert abs(expected[2]) > 0.1  # Reference sphere is not the geodetic ellipsoid.
    assert np.isnan(result.mapping_error_deg[0])


def test_invalid_orbit_rows_are_not_dropped_or_converted():
    timestamp = datetime(2018, 5, 1, tzinfo=timezone.utc)
    orbit = OrbitResult(np.array([np.nan]), np.array([np.nan]), np.array([np.nan]), np.array([6]), "test")
    for backend in ("aacgmv2", "apexpy"):
        result = convert_magnetic(backend, (timestamp,), orbit)
        assert result.error_codes.tolist() == [2]
        assert audit_magnetic_result(result, orbit)["passed"]


def test_integrity_rejects_mlt_wrap_and_wrong_unit_field():
    from dataclasses import replace

    timestamp = datetime(2018, 5, 1, tzinfo=timezone.utc)
    orbit = OrbitResult(np.array([45.]), np.array([-77.]), np.array([500.]), np.array([0]), "test")
    result = convert_magnetic("aacgmv2", (timestamp,), orbit)
    assert not audit_magnetic_result(replace(result, local_time_hours=np.array([24.])), orbit)["passed"]
    assert not audit_magnetic_result(replace(result, mapping_error_deg=result.surface_altitude_km), orbit)["passed"]
