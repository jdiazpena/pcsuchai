"""Independent scalar reference checks for saved centroid and timeline summaries."""

from __future__ import annotations

import math
import sys


def _number(value) -> bool:
    """Accept finite real JSON scalars, excluding booleans and missing values."""

    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def validate_centroid(spec, selection, measurements, saved) -> dict:
    """Check a saved weighted centroid without calling its production function.

    Scalar math.fsum/trigonometric references are independent of the NumPy
    vector reductions. Tolerances (1e-10 degrees, 1e-12 relative total) are
    numerical audit thresholds, not estimates of physical location accuracy.
    """

    if not isinstance(saved, dict):
        return {"passed": False, "reason": "requested centroid metadata missing"}
    indices = [index for index, included in enumerate(selection.mask) if included]
    weights = [float(measurements.particle_counts[index]) for index in indices]
    latitude = [float(selection.y[index]) for index in indices]
    longitude = [float(selection.x[index]) for index in indices]
    defined = bool(weights) and all(math.isfinite(value) and value >= 0 for value in weights) and any(value > 0 for value in weights)
    defined = defined and all(math.isfinite(value) for value in latitude + longitude)
    expected_latitude = expected_longitude = total = None
    if defined:
        maximum = max(weights)
        normalized = [weight / maximum for weight in weights]
        denominator = math.fsum(normalized)
        sine = math.fsum(weight * math.sin(math.radians(angle)) for weight, angle in zip(normalized, longitude)) / denominator
        cosine = math.fsum(weight * math.cos(math.radians(angle)) for weight, angle in zip(normalized, longitude)) / denominator
        defined = math.hypot(sine, cosine) > 64 * sys.float_info.epsilon
        if defined:
            expected_latitude = math.fsum(weight * angle for weight, angle in zip(normalized, latitude)) / denominator
            expected_longitude = math.degrees(math.atan2(sine, cosine))
            try:
                total = math.fsum(weights)
            except OverflowError:
                pass
    checks = {"name": saved.get("plot_name") == spec.name,
              "required_fields": {"latitude_deg", "longitude_deg", "total_particle_count"} <= saved.keys(),
              "coordinate_view": saved.get("coordinate_view") == spec.coordinate_view,
              "points": type(saved.get("points")) is int and saved["points"] == len(indices),
              "status": saved.get("status") == ("available" if defined else "unavailable")}
    if defined:
        actual_latitude, actual_longitude = saved.get("latitude_deg"), saved.get("longitude_deg")
        checks["latitude"] = _number(actual_latitude) and abs(actual_latitude - expected_latitude) <= 1e-10
        checks["longitude"] = _number(actual_longitude) and -180 <= actual_longitude <= 180 and abs((actual_longitude - expected_longitude + 180) % 360 - 180) <= 1e-10
        actual_total = saved.get("total_particle_count")
        checks["total"] = (actual_total is None and saved.get("total_particle_count_status") == "overflow_float64") if total is None else (
            _number(actual_total) and math.isclose(actual_total, total, rel_tol=1e-12, abs_tol=0)
            and saved.get("total_particle_count_status", "available") == "available")
    else:
        checks["null_coordinates_and_total"] = all(saved.get(key) is None for key in ("latitude_deg", "longitude_deg", "total_particle_count"))
        checks["reason"] = isinstance(saved.get("reason"), str) and bool(saved["reason"])
    return {"passed": all(checks.values()), "checks": checks, "expected_status": "available" if defined else "unavailable",
            "angular_tolerance_deg": 1e-10, "total_relative_tolerance": 1e-12,
            "scope": "scalar_reference_on_exact_saved_selection_not_absolute_orbit_accuracy"}


def validate_analysis_metadata(spec, selection, measurements, saved) -> dict:
    """Validate selected counts/ranges, UTC timeline endpoints and centroid policy."""

    indices = [index for index, included in enumerate(selection.mask) if included]
    checks = {"points_rendered": type(saved.get("points_rendered")) is int and saved["points_rendered"] == len(indices),
              "data_status": saved.get("data_status") == ("available" if indices else "empty_selection"),
              "variable": saved.get("variable") == spec.variable,
              "coordinate_view": saved.get("coordinate_view") == spec.coordinate_view}
    if spec.plot_type == "time_availability":
        times = [measurements.times[index] for index in indices]
        checks.update(plot_type=saved.get("plot_type") == "time_availability",
                      explicit_time_fields={"first_time_utc", "last_time_utc"} <= saved.keys(),
                      first_time_utc=saved.get("first_time_utc") == (min(times).isoformat() if times else None),
                      last_time_utc=saved.get("last_time_utc") == (max(times).isoformat() if times else None))
    else:
        values = [float(selection.values[index]) for index in indices]
        checks["scale"] = saved.get("scale") == selection.scale
        for key, expected in (("value_min", min(values) if values else None), ("value_max", max(values) if values else None)):
            actual = saved.get(key)
            checks[key] = actual is None if expected is None else _number(actual) and actual == expected
    centroid = validate_centroid(spec, selection, measurements, saved.get("particle_weighted_centroid")) if spec.calculate_centroid else None
    checks["centroid"] = centroid["passed"] if centroid is not None else "particle_weighted_centroid" not in saved
    return {"passed": all(checks.values()), "checks": checks, "centroid": centroid, "verifier_version": 1}
