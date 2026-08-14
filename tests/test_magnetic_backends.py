from datetime import datetime, timezone

import numpy as np

from pcsuchai.magnetic import convert_magnetic
from pcsuchai.models import OrbitResult
from pcsuchai.validation import compare_magnetic


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
        assert np.all(result.error_codes == 0)
        assert np.all(np.isfinite(result.latitude_deg))
        assert np.all((-90 <= result.latitude_deg) & (result.latitude_deg <= 90))
        assert np.all((0 <= result.local_time_hours) & (result.local_time_hours < 24))
    comparison = compare_magnetic(aacgm, apex)
    assert comparison["positions_compared"] == 2
    assert "not accuracy errors" in comparison["interpretation"]


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
