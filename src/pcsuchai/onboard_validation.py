"""Small onboard summaries and checks that do not require saved science arrays.

    Counts and in-memory domain checks support operational completion. They do
    not establish numerical equality with a reference or reconstruct plot masks.
    Detailed scientific acceptance uses the separate validation output policy.
"""

from __future__ import annotations

import hashlib

import numpy as np

from .product_validation import validate_image


def source_rows_digest(rows) -> str:
    """Identify selected original rows with a fixed-endian hash, not a row list."""

    return hashlib.sha256(np.asarray(rows, dtype="<i8").tobytes()).hexdigest()


def audit_orbit_result(orbit, rows: int) -> dict:
    """Check orbit rows, error codes, finite/NaN masks and geographic ranges."""

    names = ("latitude_deg", "longitude_deg", "altitude_km", "error_codes")
    checks = {"row_shapes_match": all(np.asarray(getattr(orbit, name)).shape == (rows,) for name in names),
              "backend": orbit.backend in ("astropy", "skyfield")}
    if checks["row_shapes_match"]:
        valid = orbit.error_codes == 0
        checks.update(integer_codes=np.asarray(orbit.error_codes).dtype.kind == "i",
                      known_error_codes=bool(np.all(np.isin(orbit.error_codes, range(7)))),
                      finite_valid_nan_invalid=all(bool(np.all(np.isfinite(getattr(orbit, name)[valid]))
                                                       and np.all(np.isnan(getattr(orbit, name)[~valid])))
                                                   for name in names[:3]),
                      latitude_range=bool(np.all(np.abs(orbit.latitude_deg[valid]) <= 90)),
                      longitude_range=bool(np.all(np.abs(orbit.longitude_deg[valid]) <= 180)))
        codes, counts = np.unique(orbit.error_codes, return_counts=True)
        error_counts = {str(int(code)): int(count) for code, count in zip(codes, counts)}
        valid_rows = int(np.count_nonzero(valid))
    else:
        error_counts, valid_rows = {}, 0
    return {"passed": all(checks.values()), "checks": checks, "rows": rows,
            "valid_rows": valid_rows, "invalid_rows": rows - valid_rows,
            "error_counts": error_counts, "backend": orbit.backend,
            "scope": "in_memory_domain_checks_not_independent_numerical_validation"}


def _count(value, rows: int) -> bool:
    """Counts must be integer row totals, excluding bools and impossible values."""

    return type(value) is int and 0 <= value <= rows


def validate_onboard_manifest(manifest: dict, *, stages=None, specs=None,
                             measurements=None, path_resolver=None) -> dict:
    """Verify recorded completion, domain summaries, plot counts/recipes and PNGs.

    Domain checks are recorded by the worker while its arrays exist. Saved-image
    checks decode files but cannot independently count overlapping points. No
    post-run report treats these summaries as a numerical-fidelity certificate.
    """

    rows = manifest.get("observations")
    if type(rows) is not int or rows <= 0:
        return {"passed": False, "checks": {"nonempty_rows": False}, "images": []}
    checks = {"output_policy": manifest.get("output_policy") == "onboard",
              "completed": manifest.get("status") == "complete" and manifest.get("error") is None,
              "settings_policy": manifest.get("settings", {}).get("output_policy") == "onboard",
              "settings_backends": all(manifest.get("settings", {}).get(key) == manifest.get(key)
                                       for key in ("orbit_backend", "magnetic_backend")),
              "no_raw_science": manifest.get("raw_products_npz") is None and not manifest.get("plot_selection_files"),
              "orbit_counts": _count(manifest.get("valid_positions"), rows)
                              and _count(manifest.get("invalid_positions"), rows)
                              and manifest.get("valid_positions", 0) + manifest.get("invalid_positions", 0) == rows,
              "inputs": all(isinstance(manifest.get("inputs", {}).get(k), str)
                            for k in ("measurements", "tle", "eop", "plot_config"))}
    for role, backend in (("orbit_integrity", manifest.get("orbit_backend")),
                          ("magnetic_integrity", manifest.get("magnetic_backend"))):
        if role == "magnetic_integrity" and backend == "none":
            continue
        if role == "magnetic_integrity":
            checks["magnetic_counts"] = (_count(manifest.get("valid_magnetic_positions"), rows)
                                         and _count(manifest.get("invalid_magnetic_positions"), rows)
                                         and manifest.get("valid_magnetic_positions", 0)
                                         + manifest.get("invalid_magnetic_positions", 0) == rows)
        audit = manifest.get(role) or {}
        counts = audit.get("error_counts", {})
        checks[role] = (audit.get("passed") is True and bool(audit.get("checks"))
                        and all(value is True for value in audit["checks"].values())
                        and audit.get("rows") == rows and audit.get("backend") == backend
                        and _count(audit.get("valid_rows"), rows) and _count(audit.get("invalid_rows"), rows)
                        and audit.get("valid_rows", 0) + audit.get("invalid_rows", 0) == rows
                        and isinstance(counts, dict) and bool(counts)
                        and all(_count(n, rows) for n in counts.values()) and sum(counts.values()) == rows
                        and counts.get("0", 0) == audit.get("valid_rows")
                        and audit.get("valid_rows") == manifest.get("valid_positions" if role == "orbit_integrity"
                                                                     else "valid_magnetic_positions"))
    selection = manifest.get("workload_selection", {})
    checks["selected_rows"] = selection.get("selected_rows") == rows and "source_rows" not in selection
    if measurements is not None:
        checks["input_row_identity"] = len(measurements) == rows and selection.get("source_rows_sha256") == source_rows_digest(measurements.source_rows)
    configured = manifest.get("configured_plots", [])
    checks["configured_metadata"] = isinstance(configured, list)
    if not checks["configured_metadata"]:
        return {"passed": False, "checks": checks, "images": []}
    if specs is not None:
        from .plot_config import plot_spec_metadata
        checks["frozen_recipes"] = ([image.get("spec") for image in configured]
                                     == [plot_spec_metadata(spec) for spec in specs])
    images = []
    roles = [("plot", True)]
    if manifest.get("magnetic_backend") != "none":
        roles += [("magnetic_plot", False), ("footpoint_plot", True)]
    for role, geographic in roles:
        metadata = manifest.get(role) or {}
        count = metadata.get("selected_count")
        checks[f"count:{role}"] = _count(count, rows)
        if checks[f"count:{role}"]:
            images.append(validate_image(metadata, count, geographic=geographic, path_resolver=path_resolver))
    for index, metadata in enumerate(configured):
        count = metadata.get("selected_count")
        checks[f"count:configured:{index}"] = _count(count, rows)
        integrity = metadata.get("selection_integrity") or {}
        checks[f"selection:configured:{index}"] = (set(integrity) == {"mask_boolean", "row_shapes_match", "selected_values_finite"}
                                                   and all(value is True for value in integrity.values()))
        if checks[f"count:configured:{index}"]:
            images.append(validate_image(metadata, count, geographic=metadata.get("plot_type") != "time_availability"
                                          and metadata.get("coordinate_view") in ("geographic", "footpoint"), path_resolver=path_resolver))
    required = ["load_measurements", "load_and_select_tles", "propagate_orbit"]
    if manifest.get("magnetic_backend") != "none":
        required.append("convert_magnetic_coordinates")
    required.append("render_and_write_plot")
    if manifest.get("magnetic_backend") != "none":
        required += ["render_and_write_magnetic_plot", "render_and_write_footpoint_plot"]
    required += [f"render_configured_plot:{item.get('spec', {}).get('name')}" for item in configured]
    checks["stage_order"] = manifest.get("completed_stages") == required
    if stages is not None:
        order = [row.get("stage") for row in stages if isinstance(row, dict)]
        checks["stage_timing_records"] = order == ([] if manifest.get("instrumentation", {}).get("level") == "minimal" else required)
    return {"passed": all(checks.values()) and len(images) == len(roles) + len(configured)
            and all(image["passed"] for image in images), "checks": checks, "images": images,
            "configured_selection_count_matches": True,
            "scope": "saved_onboard_settings_counts_images_and_recorded_domain_checks",
            "numerical_fidelity": "unavailable_without_per_row_scientific_products"}
