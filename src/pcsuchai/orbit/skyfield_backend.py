"""Skyfield TLE propagation and WGS84 geodetic conversion."""

from __future__ import annotations

import numpy as np

from ..errors import BackendUnavailableError
from ..models import OrbitResult, TLERecord, TLESelection


def propagate_skyfield(times, records: tuple[TLERecord, ...], selection: TLESelection) -> OrbitResult:
    """Return WGS84 geodetic coordinates using Skyfield entirely offline."""

    try:
        from skyfield.api import EarthSatellite, load, wgs84
    except ImportError as exc:
        raise BackendUnavailableError('Skyfield orbit backend unavailable; install ".[orbit-skyfield]"') from exc

    timescale = load.timescale(builtin=True)
    count = len(times)
    latitude = np.full(count, np.nan)
    longitude = np.full(count, np.nan)
    altitude = np.full(count, np.nan)
    errors = np.zeros(count, dtype=np.int16)

    for tle_index in np.unique(selection.indices):
        positions = np.flatnonzero(selection.indices == tle_index)
        try:
            satellite = EarthSatellite(
                records[int(tle_index)].line1,
                records[int(tle_index)].line2,
                f"SUCHAI-1-{tle_index}",
                timescale,
            )
            current_times = timescale.from_datetimes([times[int(i)] for i in positions])
            geographic = wgs84.geographic_position_of(satellite.at(current_times))
            latitude[positions] = geographic.latitude.degrees
            longitude[positions] = geographic.longitude.degrees
            altitude[positions] = geographic.elevation.km
        except (ValueError, OverflowError):
            errors[positions] = -1

    return OrbitResult(latitude, longitude, altitude, errors, "skyfield")
