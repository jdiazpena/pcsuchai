"""ApexPy modified-apex coordinates and field-line mappings."""

from __future__ import annotations

import numpy as np

from ..models import MagneticResult, OrbitResult


def convert_apexpy(times: tuple, orbit: OrbitResult) -> MagneticResult:
    """Convert each valid WGS84 position to modified-apex coordinates.

    A date-specific ``Apex`` object is used for every observation. This avoids
    silently quantizing the magnetic model epoch and intentionally measures the
    full cost of scientifically faithful onboard processing.
    """

    try:
        from apexpy import Apex
    except ImportError as exc:
        raise RuntimeError("Apex processing requires the apexpy package") from exc

    count = len(times)
    latitude = np.full(count, np.nan)
    longitude = np.full(count, np.nan)
    local_time = np.full(count, np.nan)
    surface_latitude = np.full(count, np.nan)
    surface_longitude = np.full(count, np.nan)
    mapping_error = np.full(count, np.nan)
    errors = np.full(count, 3, dtype=np.int16)

    for index, timestamp in enumerate(times):
        if orbit.error_codes[index] != 0:
            errors[index] = 2
            continue
        try:
            converter = Apex(date=timestamp)
            glat = float(orbit.latitude_deg[index])
            glon = float(orbit.longitude_deg[index])
            height = float(orbit.altitude_km[index])
            mlat, mlon = converter.convert(
                glat, glon, "geo", "apex", height=height, datetime=timestamp
            )
            _, mlt = converter.convert(
                glat, glon, "geo", "mlt", height=height, datetime=timestamp
            )
            slat, slon, residual = converter.map_to_height(glat, glon, height, 0.0)
            values = (mlat, mlon, mlt, slat, slon)
            if not np.all(np.isfinite(values)):
                errors[index] = 1
                continue
            latitude[index], longitude[index], local_time[index] = mlat, mlon, mlt
            surface_latitude[index], surface_longitude[index] = slat, slon
            mapping_error[index] = residual
            errors[index] = 0
        except (ValueError, RuntimeError, OverflowError):
            continue

    return MagneticResult(
        latitude, longitude, local_time, surface_latitude, surface_longitude,
        mapping_error, errors, "apexpy", "modified_apex",
    )
