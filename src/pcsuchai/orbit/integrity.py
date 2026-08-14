"""Earth-orientation and offline time-data integrity checks."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import numpy as np

from ..benchmark import sha256_file


def audit_eop_coverage(path: str | Path, observation_times: tuple) -> dict:
    """Require finite local EOP interpolation for every observation time."""

    from astropy.time import Time
    from astropy.utils import iers
    from astropy.utils.iers import IERS_A, IERSRangeError

    source = Path(path)
    iers.conf.auto_download = False
    table = IERS_A.open(str(source))
    times = Time(list(observation_times), scale="utc")
    table_mjd = np.asarray(table["MJD"].value, dtype=float)
    try:
        ut1 = np.asarray(table.ut1_utc(times).value, dtype=float)
        pm_x, pm_y = table.pm_xy(times)
        finite = np.isfinite(ut1) & np.isfinite(pm_x.value) & np.isfinite(pm_y.value)
        interpolation_error = None
    except IERSRangeError as exc:
        finite = np.zeros(len(observation_times), dtype=bool)
        interpolation_error = str(exc)
    observation_mjd = np.asarray(times.mjd, dtype=float)
    coverage = bool(observation_mjd.min() >= table_mjd.min() and observation_mjd.max() <= table_mjd.max())
    return {
        "status": "pass" if coverage and bool(np.all(finite)) else "fail",
        "path": str(source), "sha256": sha256_file(source),
        "table_rows": len(table), "table_mjd_minimum": float(table_mjd.min()),
        "table_mjd_maximum": float(table_mjd.max()),
        "observation_mjd_minimum": float(observation_mjd.min()),
        "observation_mjd_maximum": float(observation_mjd.max()),
        "observations": len(observation_times),
        "finite_interpolations": int(np.count_nonzero(finite)),
        "coverage_passed": coverage, "interpolation_error": interpolation_error,
        "automatic_downloads_enabled": bool(iers.conf.auto_download),
    }


def skyfield_time_data_provenance() -> dict:
    """Hash the bundled Skyfield time tables used in offline mode."""

    records = {}
    for name in ("iers.npz", "delta_t.npz", "nutation.npz"):
        resource = files("skyfield.data").joinpath(name)
        with resource.open("rb") as handle:
            data = handle.read()
        import hashlib

        records[name] = {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return {"builtin_timescale": True, "files": records}


def validate_sgp4_reference_vector() -> dict:
    """Check the installed SGP4 implementation against Vallado satellite 00005."""

    from sgp4.api import Satrec

    line1 = "1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753"
    line2 = "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667"
    expected_position = np.asarray((7022.46529266, -1400.08296755, 0.03995155))
    expected_velocity = np.asarray((1.893841015, 6.405893759, 4.534807250))
    satellite = Satrec.twoline2rv(line1, line2)
    error, position, velocity = satellite.sgp4(satellite.jdsatepoch, satellite.jdsatepochF)
    position_error = np.abs(np.asarray(position) - expected_position)
    velocity_error = np.abs(np.asarray(velocity) - expected_velocity)
    position_limit_km = 1e-7
    velocity_limit_km_s = 1e-9
    passed = (
        error == 0 and float(position_error.max()) <= position_limit_km
        and float(velocity_error.max()) <= velocity_limit_km_s
    )
    return {
        "status": "pass" if passed else "fail", "satellite_number": "00005",
        "reference": "Vallado/CelesTrak SGP4 verification case at epoch",
        "sgp4_error_code": int(error),
        "maximum_position_component_error_km": float(position_error.max()),
        "position_component_limit_km": position_limit_km,
        "maximum_velocity_component_error_km_s": float(velocity_error.max()),
        "velocity_component_limit_km_s": velocity_limit_km_s,
    }
