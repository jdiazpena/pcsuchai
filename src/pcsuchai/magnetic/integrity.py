"""Model-specific domain and unit invariants, not cross-model equality."""

from __future__ import annotations

import numpy as np

from ..models import MagneticResult, OrbitResult


def audit_magnetic_result(result: MagneticResult, orbit: OrbitResult) -> dict:
    """Check complete row masks, coordinate ranges and mapping-unit semantics.

    Each backend is audited on its own successful/invalid rows. Inverse API
    agreement and reference-case accuracy require separate tests; these range
    and mask checks alone cannot prove that a magnetic model is accurate.
    """

    count = len(orbit.error_codes)
    coordinate_fields = (
        "latitude_deg", "longitude_deg", "local_time_hours", "surface_latitude_deg",
        "surface_longitude_deg", "surface_altitude_km",
    )
    checks = {"row_lengths_match": all(
        np.asarray(getattr(result, name)).shape == (count,)
        for name in (*coordinate_fields, "mapping_error_deg", "error_codes")
    )}
    if not checks["row_lengths_match"]:
        return {"passed": False, "checks": checks, "backend": result.backend, "rows": count}
    valid = result.error_codes == 0
    finite = np.logical_and.reduce([np.isfinite(getattr(result, name)) for name in coordinate_fields])
    checks.update({
        "known_error_codes": bool(np.all(np.isin(result.error_codes, [0, 1, 2, 3]))),
        "valid_mask_matches_finite_coordinates": bool(np.array_equal(valid, finite)),
        "invalid_coordinates_are_nan": all(np.all(np.isnan(getattr(result, name)[~valid])) for name in coordinate_fields),
        "invalid_orbit_propagated": bool(np.array_equal(result.error_codes == 2, orbit.error_codes != 0)),
        "latitude_range_deg": bool(np.all(np.abs(result.latitude_deg[valid]) <= 90)),
        "longitude_range_deg": bool(np.all(np.abs(result.longitude_deg[valid]) <= 180)),
        "footpoint_latitude_range_deg": bool(np.all(np.abs(result.surface_latitude_deg[valid]) <= 90)),
        "footpoint_longitude_range_deg": bool(np.all(np.abs(result.surface_longitude_deg[valid]) <= 180)),
        "mlt_range_hours": bool(np.all((result.local_time_hours[valid] >= 0) & (result.local_time_hours[valid] < 24))),
    })
    if result.backend == "aacgmv2":
        checks["coordinate_definition"] = result.coordinate_system == "aacgm"
        checks["angular_residual_unavailable"] = bool(np.all(np.isnan(result.mapping_error_deg)))
        # 6371.2 km reference sphere differs from WGS84's surface by less than
        # 22 km. A generous 30 km diagnostic bound is not a map-accuracy score.
        checks["reference_sphere_altitude_km"] = bool(np.all(np.abs(result.surface_altitude_km[valid]) < 30))
    elif result.backend == "apexpy":
        checks["coordinate_definition"] = result.coordinate_system == "modified_apex"
        checks["angular_residual_available"] = bool(np.all(np.isfinite(result.mapping_error_deg[valid])))
        checks["zero_geodetic_height_km"] = bool(np.all(result.surface_altitude_km[valid] == 0))
    else:
        checks["known_backend"] = False
    codes, amounts = np.unique(result.error_codes, return_counts=True)
    return {"passed": all(checks.values()), "checks": checks, "backend": result.backend,
            "rows": count, "valid_rows": int(valid.sum()), "invalid_rows": int((~valid).sum()),
            "error_counts": {str(int(code)): int(amount) for code, amount in zip(codes, amounts)},
            "interpretation": "Each model's masks/units/ranges; not absolute accuracy or cross-model equality."}
