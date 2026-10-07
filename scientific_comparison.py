"""Same-backend scientific fidelity from retained, unrounded numeric products.

This compares software results, not absolute physical accuracy. ApexPy and
AACGMv2 are distinct coordinate models and are never scored for equality.
Every trusted value, source row, TLE assignment, invalid mask and plot decision
must agree exactly. Frozen small envelopes apply only to derived floating-point
coordinates; they are never widened automatically to make a run pass.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .magnetic.integrity import audit_magnetic_result
from .models import MagneticResult, Measurements, OrbitResult, TLESelection


POLICY_VERSION = 1
COORDINATE_RULES = {
    "orbit_latitude_deg": (1e-7, None, "degrees"),
    "orbit_longitude_deg": (1e-7, 360.0, "degrees"),
    "orbit_altitude_km": (1e-6, None, "kilometres"),
    "magnetic_latitude_deg": (2.5e-4, None, "degrees"),
    "magnetic_longitude_deg": (2.5e-4, 360.0, "degrees"),
    "magnetic_surface_latitude_deg": (2.5e-4, None, "degrees"),
    "magnetic_surface_longitude_deg": (2.5e-4, 360.0, "degrees"),
    "magnetic_mapping_error_deg": (2.5e-4, None, "degrees"),
    "magnetic_local_time_hours": (3.1e-5, 24.0, "hours"),
    "magnetic_surface_altitude_km": (1e-5, None, "kilometres"),
}
BASE_KEYS = {f"measurement_{field.name}" for field in fields(Measurements)}
BASE_KEYS |= {f"tle_selection_{field.name}" for field in fields(TLESelection)}
BASE_KEYS |= {f"orbit_{field.name}" for field in fields(OrbitResult)}
BASE_KEYS |= {"particle_threshold", "geographic_particle_map_mask"}
MAGNETIC_KEYS = {f"magnetic_{field.name}" for field in fields(MagneticResult)}
MAGNETIC_KEYS |= {"magnetic_particle_map_mask", "footpoint_particle_map_mask"}


def tolerance_policy() -> dict:
    """Return the frozen regression envelopes and their precision rationale.

    The orbit envelope is centimetre-scale or smaller, much tighter than the
    existing cross-wrapper 0.01-degree/0.1-km consistency gate. The magnetic
    angular/hour envelopes approximate sixteen float32 spacings at 180 degrees
    and 24 hours, respectively, accommodating single-precision Apex interfaces.
    They are engineering fidelity limits, not demonstrated ARM error bounds or
    model accuracy estimates; each actual board must still pass acceptance.
    """

    return {"version": POLICY_VERSION, "relative_tolerance": 0.0,
            "trusted_values_and_masks": "exact, including NaN/+inf/-inf identities",
            "integer_width": "32/64-bit signed widths may differ; values must match without float coercion",
            "derived_coordinates": {key: {"absolute_tolerance": tolerance, "wrap_period": period, "unit": unit}
                                    for key, (tolerance, period, unit) in COORDINATE_RULES.items()},
            "rationale": "centimetre-scale same-orbit fidelity; magnetic envelopes approximately 16 float32 spacings at 180 degrees/24 hours; no automatic widening",
            "limit": "relative software fidelity, not absolute orbit/magnetic accuracy or demonstrated cross-board acceptance"}


def compare_array(first: np.ndarray, second: np.ndarray, *, tolerance: float = 0.0,
                  period: float | None = None, exact: bool = True) -> dict:
    """Compare values/shapes/types with exact non-finite identity and safe integers.

    Signed integer widths and Unicode widths may differ across 32/64-bit builds;
    dtype kinds still must agree. Floats must retain their precision. No integer
    count is converted to float, and wrapped differences apply only to finite
    derived angles. Overflow is an explicit failed comparison, not JSON infinity.
    """

    first, second = np.asarray(first), np.asarray(second)
    checks = {"shape": first.shape == second.shape, "dtype_kind": first.dtype.kind == second.dtype.kind}
    if first.dtype.kind == "f" and second.dtype.kind == "f":
        checks["float_precision_preserved"] = first.dtype.itemsize == second.dtype.itemsize
    checks["supported_type"] = first.dtype.kind in "biufUS" and second.dtype.kind in "biufUS"
    result = {"reference_dtype": str(first.dtype), "candidate_dtype": str(second.dtype),
              "reference_shape": list(first.shape), "candidate_shape": list(second.shape),
              "checks": checks, "absolute_tolerance": 0.0 if exact else tolerance, "period": period}
    if not all(checks.values()):
        return {**result, "passed": False}
    if first.dtype.kind != "f":
        checks["values_exact"] = bool(np.array_equal(first, second))
        result["changed_values"] = int(np.count_nonzero(first != second))
    else:
        checks["nan_mask"] = bool(np.array_equal(np.isnan(first), np.isnan(second)))
        checks["positive_infinity_mask"] = bool(np.array_equal(np.isposinf(first), np.isposinf(second)))
        checks["negative_infinity_mask"] = bool(np.array_equal(np.isneginf(first), np.isneginf(second)))
        joint = np.isfinite(first) & np.isfinite(second)
        if exact:
            checks["values_exact"] = bool(np.array_equal(first, second, equal_nan=True))
            result["changed_finite_values"] = int(np.count_nonzero(first[joint] != second[joint]))
        else:
            with np.errstate(over="ignore", invalid="ignore"):
                difference = first[joint] - second[joint]
                if period is not None:
                    difference = (difference + period / 2) % period - period / 2
                absolute = np.abs(difference)
            checks["finite_differences"] = bool(np.all(np.isfinite(absolute)))
            checks["within_tolerance"] = bool(np.all(absolute <= tolerance))
            result.update(finite_values_compared=int(np.count_nonzero(joint)),
                          changed_finite_values=int(np.count_nonzero(absolute)),
                          above_tolerance=int(np.count_nonzero(absolute > tolerance)),
                          maximum_absolute_difference=float(np.max(absolute)) if absolute.size and checks["finite_differences"] else None,
                          p95_absolute_difference=float(np.quantile(absolute, 0.95)) if absolute.size and checks["finite_differences"] else None)
    return {**result, "passed": all(checks.values())}


def audit_raw_products(arrays: dict, *, require_magnetic: bool = True) -> dict:
    """Check retained row schema, UTC/frame/unit conventions and own-model masks."""

    required = BASE_KEYS | (MAGNETIC_KEYS if require_magnetic else set())
    checks = {"required_fields": required <= arrays.keys()}
    if not checks["required_fields"]:
        return {"passed": False, "checks": checks, "missing_fields": sorted(required - arrays.keys())}
    rows = arrays["measurement_source_rows"]
    count = rows.size
    checks["row_ids"] = rows.ndim == 1 and rows.dtype.kind == "i" and bool(np.all(rows > 0)) and len(np.unique(rows)) == count
    row_fields = {key for key in required if key not in ("orbit_backend", "particle_threshold", "magnetic_backend", "magnetic_coordinate_system")}
    checks["row_shapes"] = all(arrays[key].shape == (count,) for key in row_fields)
    if not checks["row_shapes"]:
        return {"passed": False, "checks": checks, "rows": count}
    checks["integer_codes"] = all(arrays[key].dtype.kind == "i" for key in ("orbit_error_codes", "tle_selection_indices"))
    checks["tle_assignments"] = bool(np.all(arrays["tle_selection_indices"] >= 0) and np.all(np.isfinite(arrays["tle_selection_offset_seconds"])))
    checks["boolean_plot_masks"] = all(arrays[key].dtype == bool for key in required if key.endswith("_mask"))
    try:
        timestamps = [datetime.fromisoformat(str(value)) for value in arrays["measurement_times"]]
        checks["utc_times"] = all(value.tzinfo is not None and value.utcoffset() == timezone.utc.utcoffset(value) for value in timestamps)
    except (ValueError, TypeError):
        checks["utc_times"] = False
    valid = arrays["orbit_error_codes"] == 0
    for key in ("orbit_latitude_deg", "orbit_longitude_deg", "orbit_altitude_km"):
        checks[f"finite_valid_nan_invalid:{key}"] = bool(np.all(np.isfinite(arrays[key][valid])) and np.all(np.isnan(arrays[key][~valid])))
    checks["geographic_latitude_range"] = bool(np.all(np.abs(arrays["orbit_latitude_deg"][valid]) <= 90))
    checks["geographic_longitude_range"] = bool(np.all(np.abs(arrays["orbit_longitude_deg"][valid]) <= 180))
    checks["orbit_backend"] = arrays["orbit_backend"].shape == () and str(arrays["orbit_backend"].item()) in ("astropy", "skyfield")
    magnetic_audit = None
    if require_magnetic:
        checks["magnetic_scalars"] = all(arrays[key].shape == () for key in ("magnetic_backend", "magnetic_coordinate_system"))
        if checks["magnetic_scalars"]:
            orbit = OrbitResult(**{field.name: (arrays[f"orbit_{field.name}"].item() if field.name == "backend" else arrays[f"orbit_{field.name}"])
                                   for field in fields(OrbitResult)})
            magnetic = MagneticResult(**{field.name: (arrays[f"magnetic_{field.name}"].item() if field.name in ("backend", "coordinate_system") else arrays[f"magnetic_{field.name}"])
                                         for field in fields(MagneticResult)})
            magnetic_audit = audit_magnetic_result(magnetic, orbit)
            checks["own_model_invariants"] = magnetic_audit["passed"]
    return {"passed": all(checks.values()), "checks": checks, "rows": count, "magnetic_audit": magnetic_audit}


def _read_npz(path: str | Path) -> dict:
    """Read unrounded arrays without pickle and reject ambiguous duplicate keys."""

    with np.load(path, allow_pickle=False) as archive:
        if len(archive.files) != len(set(archive.files)):
            raise ValueError("duplicate array names in retained NPZ")
        return {key: archive[key] for key in archive.files}


def compare_scientific_products(reference_path: str | Path, candidate_path: str | Path, *,
                                reference_selections: tuple[str | Path, ...] = (), candidate_selections: tuple[str | Path, ...] = (),
                                expected_source_rows: np.ndarray | None = None, require_magnetic: bool = True) -> dict:
    """Compare all saved science and plot selections, not just table/image hashes.

    Cross-device comparison defaults to exact row/order identity. A selected
    workload may be validated against full-data reference arrays only when its
    frozen expected source rows are explicitly supplied; arbitrary subsets are
    not silently accepted. Coordinate model/backend strings still match exactly.
    Plot files must be supplied in matching recipe order by the caller.
    """

    reference, candidate = _read_npz(reference_path), _read_npz(candidate_path)
    audits = {"reference": audit_raw_products(reference, require_magnetic=require_magnetic),
              "candidate": audit_raw_products(candidate, require_magnetic=require_magnetic)}
    result = {"policy": tolerance_policy(), "audits": audits, "reference": str(reference_path), "candidate": str(candidate_path),
              "interpretation": "same-backend relative fidelity; no Apex/AACGM equality or absolute physical accuracy claim"}
    if not all(audit["passed"] for audit in audits.values()):
        return {**result, "passed": False, "fields": {}, "reason": "raw row/frame/unit/domain audit failed"}
    reference_rows, candidate_rows = reference["measurement_source_rows"], candidate["measurement_source_rows"]
    alignment = None
    if expected_source_rows is not None:
        expected = np.asarray(expected_source_rows)
        if not compare_array(expected, candidate_rows)["passed"] or not np.all(reference_rows[1:] > reference_rows[:-1]):
            return {**result, "passed": False, "fields": {}, "reason": "candidate selection differs from frozen expected row identity"}
        alignment = np.searchsorted(reference_rows, candidate_rows)
        if np.any(alignment >= len(reference_rows)) or not np.array_equal(reference_rows[alignment], candidate_rows):
            return {**result, "passed": False, "fields": {}, "reason": "candidate rows absent from full reference"}
    fields_report = {}
    same_keys = reference.keys() == candidate.keys()
    for key in sorted(reference.keys() & candidate.keys()):
        first, second = reference[key], candidate[key]
        if alignment is not None and first.shape == (len(reference_rows),):
            first = first[alignment]
        if key in COORDINATE_RULES:
            tolerance, period, unit = COORDINATE_RULES[key]
            comparison = {**compare_array(first, second, tolerance=tolerance, period=period, exact=False), "unit": unit}
        else:
            comparison = compare_array(first, second)
        fields_report[key] = comparison
    selections_report = []
    for reference_file, candidate_file in zip(reference_selections, candidate_selections):
        first, second = _read_npz(reference_file), _read_npz(candidate_file)
        selection_fields = {}
        for key in sorted(first.keys() & second.keys()):
            left, right = first[key], second[key]
            if alignment is not None and left.shape == (len(reference_rows),):
                left = left[alignment]
            selection_fields[key] = compare_array(left, right)
        selections_report.append({"reference": str(reference_file), "candidate": str(candidate_file), "fields": selection_fields,
                                  "passed": first.keys() == second.keys() and {"mask", "x", "y", "values"} <= first.keys() and all(item["passed"] for item in selection_fields.values())})
    result.update(fields=fields_report, field_keys_match=same_keys,
                  missing_reference_fields=sorted(candidate.keys() - reference.keys()),
                  missing_candidate_fields=sorted(reference.keys() - candidate.keys()),
                  configured_selections=selections_report,
                  configured_selection_scope="supplied recipes only" if reference_selections or candidate_selections else "not supplied",
                  passed=same_keys and all(item["passed"] for item in fields_report.values()) and
                  len(reference_selections) == len(candidate_selections) and all(item["passed"] for item in selections_report))
    return result
