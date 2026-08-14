"""AACGM-v2 magnetic coordinates and surface mappings."""

from __future__ import annotations

import numpy as np

from ..models import MagneticResult, OrbitResult


def convert_aacgmv2(times: tuple, orbit: OrbitResult) -> MagneticResult:
    """Convert each valid WGS84 position to AACGM coordinates.

    AACGM-v2's array API accepts one time for an entire array, while this data
    has a timestamp per observation. Processing rows individually preserves
    their actual observation times and provides an honest edge-compute cost.
    """

    try:
        import aacgmv2
    except ImportError as exc:
        raise RuntimeError("AACGMv2 processing requires the aacgmv2 package") from exc

    count = len(times)
    latitude = np.full(count, np.nan)
    longitude = np.full(count, np.nan)
    local_time = np.full(count, np.nan)
    surface_latitude = np.full(count, np.nan)
    surface_longitude = np.full(count, np.nan)
    mapping_error = np.full(count, np.nan)
    errors = np.full(count, 3, dtype=np.int16)

    logger_was_disabled = aacgmv2.logger.disabled
    aacgmv2.logger.disabled = True
    try:
        for index, timestamp in enumerate(times):
            if orbit.error_codes[index] != 0:
                errors[index] = 2
                continue
            try:
                mlat, mlon, mlt = aacgmv2.get_aacgm_coord(
                    float(orbit.latitude_deg[index]),
                    float(orbit.longitude_deg[index]),
                    float(orbit.altitude_km[index]),
                    timestamp,
                    method="ALLOWTRACE",
                )
                if not np.all(np.isfinite((mlat, mlon, mlt))):
                    errors[index] = 1
                    continue
                slat, slon, residual = aacgmv2.convert_latlon(
                    mlat, mlon, 0.0, timestamp, method_code="A2G|ALLOWTRACE"
                )
                if not np.all(np.isfinite((slat, slon))):
                    errors[index] = 1
                    continue
                latitude[index], longitude[index], local_time[index] = mlat, mlon, mlt
                surface_latitude[index], surface_longitude[index] = slat, slon
                mapping_error[index] = residual
                errors[index] = 0
            except (ValueError, RuntimeError, OverflowError):
                continue
    finally:
        aacgmv2.logger.disabled = logger_was_disabled

    return MagneticResult(
        latitude, longitude, local_time, surface_latitude, surface_longitude,
        mapping_error, errors, "aacgmv2", "aacgm",
    )
