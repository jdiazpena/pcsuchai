from pathlib import Path

import numpy as np

from pcsuchai.data import load_measurements
from pcsuchai.orbit import propagate
from pcsuchai.tle import load_tle_history, select_nearest_tles


ROOT = Path(__file__).parents[1]


def test_astropy_and_skyfield_agree_on_sample_positions() -> None:
    all_measurements = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")
    sample_indices = np.linspace(0, len(all_measurements) - 1, 20, dtype=int)
    times = tuple(all_measurements.times[int(index)] for index in sample_indices)
    records = load_tle_history(ROOT / "data/tle/suchai1.tle")
    selection = select_nearest_tles(times, records)

    astropy_result = propagate(
        "astropy", times, records, selection, ROOT / "data/eop/finals2000A.all"
    )
    skyfield_result = propagate("skyfield", times, records, selection)

    assert np.all(astropy_result.error_codes == 0)
    assert np.all(skyfield_result.error_codes == 0)
    assert np.max(np.abs(astropy_result.latitude_deg - skyfield_result.latitude_deg)) < 0.01
    longitude_difference = (
        astropy_result.longitude_deg - skyfield_result.longitude_deg + 180.0
    ) % 360.0 - 180.0
    assert np.max(np.abs(longitude_difference)) < 0.01
    assert np.max(np.abs(astropy_result.altitude_km - skyfield_result.altitude_km)) < 0.1
