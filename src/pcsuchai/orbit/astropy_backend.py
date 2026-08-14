"""SGP4 propagation with Astropy TEME-to-ITRS frame conversion."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import warnings

import numpy as np

from ..errors import BackendUnavailableError
from ..models import OrbitResult, TLERecord, TLESelection


def propagate_astropy(times, records: tuple[TLERecord, ...], selection: TLESelection, eop_path=None) -> OrbitResult:
    """Return WGS84 geodetic coordinates using SGP4 and Astropy.

    SGP4 produces TEME positions in kilometres using its standard WGS72 gravity
    model. Astropy transforms TEME to ITRS and reports geodetic WGS84 latitude,
    longitude, and ellipsoidal altitude. Network downloads are disabled; an
    optional local ``finals2000A`` file supplies Earth-orientation parameters.
    """

    try:
        from astropy import units as u
        from astropy.coordinates import CartesianDifferential, CartesianRepresentation, ITRS, TEME
        from astropy.time import Time
        from astropy.utils import iers
        from astropy.utils.iers import IERS_A, IERSStaleWarning, earth_orientation_table
        from sgp4.api import Satrec
    except ImportError as exc:
        raise BackendUnavailableError('Astropy orbit backend unavailable; install ".[orbit-astropy]"') from exc

    iers.conf.auto_download = False
    observation_times = Time(list(times), scale="utc")
    count = len(times)
    latitude = np.full(count, np.nan)
    longitude = np.full(count, np.nan)
    altitude = np.full(count, np.nan)
    errors = np.full(count, -1, dtype=np.int16)

    with warnings.catch_warnings():
        # The bundled table covers the 2018 observations, even though its
        # leap-second metadata is stale relative to the host's current date.
        warnings.simplefilter("ignore", IERSStaleWarning)
        context = nullcontext()
        if eop_path is not None and Path(eop_path).is_file():
            context = earth_orientation_table.set(IERS_A.open(str(eop_path)))
        with context:
            return _propagate_groups(
                observation_times, times, records, selection, latitude, longitude,
                altitude, errors, Satrec, CartesianRepresentation,
                CartesianDifferential, TEME, ITRS, u,
            )


def _propagate_groups(
    observation_times, times, records, selection, latitude, longitude, altitude,
    errors, Satrec, CartesianRepresentation, CartesianDifferential, TEME, ITRS, u,
) -> OrbitResult:
    """Propagate TLE groups while the caller's EOP context is active."""

    for tle_index in np.unique(selection.indices):
        positions = np.flatnonzero(selection.indices == tle_index)
        current_times = observation_times[positions]
        satellite = Satrec.twoline2rv(records[int(tle_index)].line1, records[int(tle_index)].line2)
        group_errors, position_km, velocity_km_s = satellite.sgp4_array(current_times.jd1, current_times.jd2)
        errors[positions] = group_errors
        valid_local = np.flatnonzero(group_errors == 0)
        if not len(valid_local):
            continue
        valid_global = positions[valid_local]
        valid_times = current_times[valid_local]
        representation = CartesianRepresentation(position_km[valid_local].T * u.km)
        differential = CartesianDifferential(velocity_km_s[valid_local].T * u.km / u.s)
        teme = TEME(representation.with_differentials(differential), obstime=valid_times)
        geodetic = teme.transform_to(ITRS(obstime=valid_times)).earth_location.geodetic
        latitude[valid_global] = geodetic.lat.to_value(u.deg)
        longitude[valid_global] = geodetic.lon.to_value(u.deg)
        altitude[valid_global] = geodetic.height.to_value(u.km)

    return OrbitResult(latitude, longitude, altitude, errors, "astropy")
