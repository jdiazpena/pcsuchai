from datetime import datetime, timedelta, timezone

import numpy as np

from pcsuchai.analysis import calculate_particle_weighted_centroid
from pcsuchai.models import MagneticResult, Measurements, OrbitResult
from pcsuchai.plot_config import PlotSpec, select_plot_data


def _inputs():
    times = tuple(datetime(2018, 8, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(6))
    sequence = np.arange(6, dtype=float)
    measurements = Measurements(
        times=times, particle_counts=np.array([0, 50, 101, 200, 300, 400], dtype=float),
        plasma_temperature=sequence + 100, plasma_voltage=sequence,
        sweep_voltage=sequence, plasma_current=sequence,
        electron_density_300k=10.0 ** (sequence + 1),
        electron_density_3000k=10.0 ** (sequence + 2),
        headers=("x",) * 6, source_rows=np.arange(2, 8),
    )
    orbit = OrbitResult(
        latitude_deg=np.array([-50, -30, -10, 10, 30, 50], dtype=float),
        longitude_deg=np.array([170, -170, -80, -40, 10, 80], dtype=float),
        altitude_km=np.full(6, 500.0), error_codes=np.zeros(6, dtype=np.int16), backend="test",
    )
    magnetic = MagneticResult(
        latitude_deg=orbit.latitude_deg + 2, longitude_deg=orbit.longitude_deg + 3,
        local_time_hours=np.array([23, 2, 7, 12, 17, 20], dtype=float),
        surface_latitude_deg=orbit.latitude_deg - 5,
        surface_longitude_deg=orbit.longitude_deg - 6,
        mapping_error_deg=np.zeros(6), error_codes=np.zeros(6, dtype=np.int16),
        backend="test", coordinate_system="test_magnetic",
    )
    return measurements, orbit, magnetic


def test_composes_time_count_day_and_geographic_filters() -> None:
    measurements, orbit, magnetic = _inputs()
    spec = PlotSpec.from_dict({
        "name": "filtered", "coordinate_view": "footpoint", "particle_gt": 100,
        "mlt_sector": "day", "geographic_latitude_min": 0,
        "include_times": [["2018-08-01T01:00:00Z", "2018-08-01T05:00:00Z"]],
        "exclude_times": [["2018-08-01T04:00:00Z", "2018-08-01T04:00:00Z"]],
    })
    selected = select_plot_data(spec, measurements, orbit, magnetic)
    assert np.flatnonzero(selected.mask).tolist() == [3]
    assert selected.x[3] == -46


def test_supports_wrapping_mlt_and_longitude_ranges() -> None:
    measurements, orbit, magnetic = _inputs()
    spec = PlotSpec.from_dict({
        "name": "wrapped", "mlt_intervals": [[21, 3]],
        "geographic_longitude_min": 160, "geographic_longitude_max": -160,
    })
    selected = select_plot_data(spec, measurements, orbit, magnetic)
    assert np.flatnonzero(selected.mask).tolist() == [0, 1]


def test_density_auto_scale_and_explicit_upper_limit() -> None:
    measurements, orbit, magnetic = _inputs()
    spec = PlotSpec.from_dict({
        "name": "density", "variable": "electron_density_300k", "value_lt": 1e5,
    })
    selected = select_plot_data(spec, measurements, orbit, magnetic)
    assert selected.scale == "log10"
    assert np.flatnonzero(selected.mask).tolist() == [0, 1, 2, 3]


def test_centroid_uses_the_same_filtered_points() -> None:
    measurements, orbit, magnetic = _inputs()
    spec = PlotSpec.from_dict({
        "name": "centroid", "coordinate_view": "footpoint", "particle_gt": 100,
        "mlt_sector": "day",
    })
    result = calculate_particle_weighted_centroid(spec, measurements, orbit, magnetic)
    assert result["points"] == 3
    assert result["coordinate_view"] == "footpoint"
    assert -20 < result["latitude_deg"] < 20
