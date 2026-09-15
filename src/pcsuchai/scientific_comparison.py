"""Same-backend fidelity of unrounded science, row identities and plot decisions.

These checks are relative software fidelity, not absolute physical accuracy.
ApexPy and AACGMv2 are distinct models, never scored for coordinate equality.
No comparison automatically widens its frozen tolerance to make data pass.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .magnetic.integrity import audit_magnetic_result
from .models import MagneticResult, Measurements, OrbitResult, TLESelection


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
BASE_KEYS = {f"measurement_{item.name}" for item in fields(Measurements)}
BASE_KEYS |= {f"tle_selection_{item.name}" for item in fields(TLESelection)}
BASE_KEYS |= {f"orbit_{item.name}" for item in fields(OrbitResult)}
BASE_KEYS |= {"particle_threshold", "geographic_particle_map_mask"}
MAGNETIC_KEYS = {f"magnetic_{item.name}" for item in fields(MagneticResult)}
MAGNETIC_KEYS |= {"magnetic_particle_map_mask", "footpoint_particle_map_mask"}


def tolerance_policy() -> dict:
    """Describe frozen regression envelopes; these are not empirical ARM bounds.

    Orbit limits are centimetre-scale or smaller and tighter than the existing
    different-wrapper 0.01-degree/0.1-km gate. Magnetic angular/hour limits are
    approximately sixteen float32 spacings at 180 degrees/24 hours, respectively,
    accounting for Apex's single-precision interfaces. Actual board acceptance
    must still demonstrate fidelity; none of these values estimates model truth.
    """

    return {"version": 1, "relative_tolerance": 0.0,
            "trusted_values_and_masks": "exact, including NaN/+inf/-inf identity",
            "integer_width": "signed widths may differ; no float coercion",
            "derived_coordinates": {key: {"absolute_tolerance": value[0], "wrap_period": value[1], "unit": value[2]}
                                    for key, value in COORDINATE_RULES.items()},
            "rationale": "centimetre-scale same-orbit fidelity; magnetic limits approximately 16 float32 spacings at 180 degrees/24 hours",
            "limit": "relative software fidelity, not absolute accuracy or demonstrated cross-board acceptance"}


def compare_array(first: np.ndarray, second: np.ndarray, *, tolerance: float = 0.0,
                  period: float | None = None, exact: bool = True) -> dict:
    """Compare shapes/types/non-finite identity and values without integer loss.

    Signed integer/Unicode widths may differ; float precision may not decrease.
    Wrapped differences use finite coordinates only. Overflow is a failed check
    with unavailable difference statistics, not non-standard JSON infinity.
    """

    first, second = np.asarray(first), np.asarray(second)
    checks = {"shape": first.shape == second.shape, "dtype_kind": first.dtype.kind == second.dtype.kind,
              "supported_type": first.dtype.kind in "biufUS" and second.dtype.kind in "biufUS"}
    if first.dtype.kind == second.dtype.kind == "f":
        checks["float_precision_preserved"] = first.dtype.itemsize == second.dtype.itemsize
    result = {"reference_dtype": str(first.dtype), "candidate_dtype": str(second.dtype),
              "reference_shape": list(first.shape), "candidate_shape": list(second.shape),
              "checks": checks, "absolute_tolerance": 0.0 if exact else tolerance, "period": period}
    if not all(checks.values()):
        return {**result, "passed": False}
    if first.dtype.kind != "f":
        checks["values_exact"] = bool(np.array_equal(first, second))
        result["changed_values"] = int(np.count_nonzero(first != second))
    else:
        for label, function in (("nan", np.isnan), ("positive_infinity", np.isposinf), ("negative_infinity", np.isneginf)):
            checks[f"{label}_mask"] = bool(np.array_equal(function(first), function(second)))
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
    """Enforce required row schema, UTC/frame/unit conventions and own-model masks."""

    required = BASE_KEYS | (MAGNETIC_KEYS if require_magnetic else set())
    checks = {"required_fields": required <= arrays.keys()}
    if not checks["required_fields"]:
        return {"passed": False, "checks": checks, "missing_fields": sorted(required - arrays.keys())}
    rows = arrays["measurement_source_rows"]
    count = rows.size
    checks["nonempty"] = count > 0
    checks["row_ids"] = rows.ndim == 1 and rows.dtype.kind == "i" and bool(np.all(rows > 0)) and len(np.unique(rows)) == count
    scalars = {"orbit_backend", "particle_threshold", "magnetic_backend", "magnetic_coordinate_system"}
    checks["row_shapes"] = all(arrays[key].shape == (count,) for key in required - scalars)
    float_fields = {key for key in required if key in COORDINATE_RULES or key == "tle_selection_offset_seconds" or
                    (key.startswith("measurement_") and key not in ("measurement_times", "measurement_headers", "measurement_source_rows"))}
    checks["float64_precision"] = all(arrays[key].dtype.kind == "f" and arrays[key].dtype.itemsize == 8 for key in float_fields)
    checks["integer_codes"] = all(arrays[key].dtype.kind == "i" for key in ("orbit_error_codes", "tle_selection_indices"))
    checks["text_fields"] = all(arrays[key].dtype.kind == "U" for key in ("measurement_times", "measurement_headers", "orbit_backend"))
    checks["boolean_plot_masks"] = all(arrays[key].dtype == bool for key in required if key.endswith("_mask"))
    checks["scalar_shapes"] = all(arrays[key].shape == () for key in required & scalars)
    checks["numeric_threshold"] = arrays["particle_threshold"].dtype.kind in "if" and bool(np.isfinite(arrays["particle_threshold"]).all())
    if not all(checks.values()):
        return {"passed": False, "checks": checks, "rows": count}
    checks["known_orbit_codes"] = bool(np.all(np.isin(arrays["orbit_error_codes"], range(7))))
    checks["tle_assignments"] = bool(np.all(arrays["tle_selection_indices"] >= 0) and np.all(np.isfinite(arrays["tle_selection_offset_seconds"])))
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
    checks["orbit_backend"] = arrays["orbit_backend"].item() in ("astropy", "skyfield")
    particle_mask = np.isfinite(arrays["measurement_particle_counts"]) & (arrays["measurement_particle_counts"] >= arrays["particle_threshold"].item())
    checks["geographic_plot_decisions"] = bool(np.array_equal(arrays["geographic_particle_map_mask"], particle_mask &
                                                               np.isfinite(arrays["orbit_latitude_deg"]) & np.isfinite(arrays["orbit_longitude_deg"])))
    magnetic_audit = None
    if require_magnetic:
        checks["magnetic_code_type"] = arrays["magnetic_error_codes"].dtype.kind == "i"
        orbit = OrbitResult(**{item.name: arrays[f"orbit_{item.name}"].item() if item.name == "backend" else arrays[f"orbit_{item.name}"] for item in fields(OrbitResult)})
        magnetic = MagneticResult(**{item.name: arrays[f"magnetic_{item.name}"].item() if item.name in ("backend", "coordinate_system") else arrays[f"magnetic_{item.name}"] for item in fields(MagneticResult)})
        magnetic_audit = audit_magnetic_result(magnetic, orbit)
        checks["own_model_invariants"] = magnetic_audit["passed"]
        base = particle_mask & (magnetic.error_codes == 0)
        for role, latitude, longitude in (("magnetic_particle_map_mask", magnetic.latitude_deg, magnetic.longitude_deg),
                                          ("footpoint_particle_map_mask", magnetic.surface_latitude_deg, magnetic.surface_longitude_deg)):
            checks[f"plot_decisions:{role}"] = bool(np.array_equal(arrays[role], base & np.isfinite(latitude) & np.isfinite(longitude)))
    return {"passed": all(checks.values()), "checks": checks, "rows": count, "magnetic_audit": magnetic_audit}


def _read_npz(path: str | Path) -> dict:
    """Read original dtype arrays without pickle; reject duplicate archive names."""

    with np.load(path, allow_pickle=False) as archive:
        if len(archive.files) != len(set(archive.files)):
            raise ValueError("duplicate array names in retained NPZ")
        return {key: archive[key] for key in archive.files}


def _selection_coordinate_rule(key: str, arrays: dict):
    """Map only known saved axis labels to their existing coordinate/unit policy."""

    label = arrays.get(f"{key}_label") if key in ("x", "y") else None
    if label is None or label.shape != ():
        return None
    axis = "longitude_deg" if key == "x" else "latitude_deg"
    name = axis.replace("_deg", "")
    labels = {f"Geographic {name} (°)": f"orbit_{axis}", f"Footpoint geographic {name} (°)": f"magnetic_surface_{axis}",
              f"modified_apex {name} (°)": f"magnetic_{axis}", f"aacgm {name} (°)": f"magnetic_{axis}"}
    return COORDINATE_RULES.get(labels.get(str(label.item())))


class _SelectionFiles:
    """Sized lazy selection sequence; only the currently compared recipes load."""

    def __init__(self, paths):
        """Retain ordered paths, never their full-data array copies."""

        self.paths = tuple(paths)

    def __len__(self):
        """Expose recipe count so missing/extra recipes still fail validation."""

        return len(self.paths)

    def __getitem__(self, index):
        """Decode one recipe without pickle; indexing preserves caller order."""

        return _read_npz(self.paths[index])


def compare_scientific_products(reference_path: str | Path, candidate_path: str | Path, *,
                                reference_selections: tuple[str | Path, ...] = (), candidate_selections: tuple[str | Path, ...] = (),
                                expected_source_rows: np.ndarray | None = None, require_magnetic: bool = True) -> dict:
    """Compare every science array and supplied plot recipe, not just hashes.

    Default cross-device comparisons require identical source rows/order. A
    selected workload can use full-data reference arrays only with its explicitly
    frozen expected rows. Plot selections are supplied in the same recipe order;
    decisions/values/labels remain exact while known derived x/y obey unit policy.
    This API does not authenticate source/input provenance or certify PNGs.
    """

    return compare_scientific_arrays(
        _read_npz(reference_path), _read_npz(candidate_path),
        reference_selections=_SelectionFiles(reference_selections),
        candidate_selections=_SelectionFiles(candidate_selections),
        expected_source_rows=expected_source_rows, require_magnetic=require_magnetic,
        reference_label=str(reference_path), candidate_label=str(candidate_path),
    )


def compare_scientific_arrays(reference: dict, candidate: dict, *, reference_selections: tuple[dict, ...] = (),
                              candidate_selections: tuple[dict, ...] = (), expected_source_rows: np.ndarray | None = None,
                              require_magnetic: bool = True, reference_label: str = "reference_arrays",
                              candidate_label: str = "candidate_arrays") -> dict:
    """Apply the same frozen policy to arrays/projected recipes without temp files.

    A full-data reference can supply a different frozen plotting profile by
    reconstructing its recipes on its own saved coordinates, then applying the
    explicit expected source-row selection. No native orbit/magnetic model is
    rerun and no rounded CSV is substituted for unrounded reference values.
    """

    audits = {"reference": audit_raw_products(reference, require_magnetic=require_magnetic),
              "candidate": audit_raw_products(candidate, require_magnetic=require_magnetic)}
    result = {"policy": tolerance_policy(), "audits": audits, "reference": reference_label, "candidate": candidate_label,
              "interpretation": "same-backend relative software fidelity, not Apex/AACGM equality or absolute accuracy"}
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
    def aligned(array):
        """Slice row-valued reference arrays only, preserving scalar metadata."""

        return array[alignment] if alignment is not None and array.shape == (len(reference_rows),) else array

    report = {}
    for key in sorted(reference.keys() & candidate.keys()):
        rule = COORDINATE_RULES.get(key)
        report[key] = compare_array(aligned(reference[key]), candidate[key], exact=rule is None,
                                    tolerance=rule[0] if rule else 0.0, period=rule[1] if rule else None)
        if rule:
            report[key]["unit"] = rule[2]
    selections = []
    for index, (first, second) in enumerate(zip(reference_selections, candidate_selections)):
        selection_fields = {}
        for key in sorted(first.keys() & second.keys()):
            rule = _selection_coordinate_rule(key, first)
            selection_fields[key] = compare_array(aligned(first[key]), second[key], exact=rule is None,
                                                  tolerance=rule[0] if rule else 0.0, period=rule[1] if rule else None)
        structure = {"mask", "x", "y", "values"} <= first.keys() and {"mask", "x", "y", "values"} <= second.keys()
        if structure:
            structure = all(arrays["mask"].dtype == bool and all(arrays[key].shape == (len(rows),) for key in ("mask", "x", "y", "values"))
                            for arrays, rows in ((first, reference_rows), (second, candidate_rows)))
            if structure:
                structure = all(np.all(np.isfinite(arrays[key][arrays["mask"]])) for arrays in (first, second) for key in ("x", "y", "values"))
        selections.append({"recipe_index": index, "fields": selection_fields, "structure_passed": bool(structure),
                           "passed": bool(structure) and first.keys() == second.keys() and all(item["passed"] for item in selection_fields.values())})
    result.update(fields=report, field_keys_match=reference.keys() == candidate.keys(),
                  missing_reference_fields=sorted(candidate.keys() - reference.keys()), missing_candidate_fields=sorted(reference.keys() - candidate.keys()),
                  configured_selections=selections, configured_selection_scope="supplied recipes only" if reference_selections or candidate_selections else "not supplied",
                  passed=reference.keys() == candidate.keys() and all(item["passed"] for item in report.values()) and
                  len(reference_selections) == len(candidate_selections) and all(item["passed"] for item in selections))
    return result
