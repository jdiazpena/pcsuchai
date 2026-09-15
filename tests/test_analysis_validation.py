"""Synthetic mathematical boundaries; native-product tests are separate."""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from pcsuchai.analysis import calculate_particle_weighted_centroid
from pcsuchai.analysis_validation import validate_centroid
from pcsuchai.plot_config import PlotSpec


@pytest.mark.parametrize("weights,longitudes,status", [
    ([1., 1.], [0., 180.], "unavailable"),
    ([0., 0.], [10., 20.], "unavailable"),
    ([-1., 3.], [10., 20.], "unavailable"),
    ([float('nan'), 1.], [10., 20.], "unavailable"),
    ([1., 1.], [179., -179.], "available"),
    ([1e308, 1e308], [10., 20.], "available"),
])
def test_centroid_boundaries_match_independent_scalar_reference(weights, longitudes, status):
    spec = PlotSpec(name="boundary", calculate_centroid=True)
    measurements = SimpleNamespace(particle_counts=np.asarray(weights))
    selected = SimpleNamespace(mask=np.array([True, True]), x=np.asarray(longitudes), y=np.array([10., 30.]))
    with patch("pcsuchai.analysis.select_plot_data", return_value=selected):
        saved = calculate_particle_weighted_centroid(spec, measurements, None, None, allow_unavailable=True)
    assert saved["status"] == status
    assert validate_centroid(spec, selected, measurements, saved)["passed"]
    if weights[0] == 1e308:
        assert saved["latitude_deg"] == 20.
        assert saved["total_particle_count"] is None
        assert saved["total_particle_count_status"] == "overflow_float64"


def test_independent_reference_rejects_arbitrary_antipodal_longitude():
    selected = SimpleNamespace(mask=np.array([True, True]), x=np.array([0., 180.]), y=np.zeros(2))
    measurements = SimpleNamespace(particle_counts=np.ones(2))
    saved = dict(status="available", plot_name="antipodal", coordinate_view="geographic", points=2,
                 latitude_deg=0., longitude_deg=90., total_particle_count=2.)
    assert not validate_centroid(PlotSpec(name="antipodal"), selected, measurements, saved)["passed"]
