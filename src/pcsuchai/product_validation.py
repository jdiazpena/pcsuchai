"""Saved-image acceptance tied to the retained scientific plot selections."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def validate_image(metadata: dict, expected_count: int, *, geographic: bool, path_resolver=None) -> dict:
    """Decode a PNG and check its declared dimensions, count and map context.

    Counts come from saved scientific masks, not the image hash. Rendering
    metadata records the actual code path/collections, not image recognition;
    this does not prove that every overlapping observation is distinguishable.
    Geographic context is verified as added land/border collections. Hashes
    remain a separate retained-byte integrity check.
    """

    checks = {"png_readable": False, "dimensions_match": False,
              "point_count_matches": metadata.get("points_rendered") == expected_count,
              "filled_markers": metadata.get("rendering", {}).get("filled_markers") is True,
              "geographic_context": not geographic}
    if expected_count == 0:
        checks["empty_selection_explicit"] = metadata.get("data_status") == "empty_selection"
    detail = {"path": metadata.get("path"), "expected_points": expected_count}
    try:
        from PIL import Image
        path = Path(metadata["path"]) if path_resolver is None else path_resolver(metadata["path"])
        detail["resolved_path"] = str(path)
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            checks["png_readable"] = image.format == "PNG"
            checks["dimensions_match"] = image.size == (metadata.get("width_px"), metadata.get("height_px"))
            detail["actual_dimensions_px"] = list(image.size)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        detail["error"] = f"{type(exc).__name__}: {exc}"
    if geographic:
        context = metadata.get("geographic_context") or {}
        checks["geographic_context"] = (
            context.get("source") == "bundled Natural Earth 110m"
            and context.get("land_parts", 0) > 0 and context.get("border_segments", 0) > 0
        )
    return {"passed": all(checks.values()), "checks": checks, **detail}


def validate_pipeline_images(manifest: dict, raw_products: str | Path, selection_files: tuple[str, ...], *, path_resolver=None) -> dict:
    """Audit all default/configured images against losslessly retained masks."""

    images = []
    with np.load(raw_products, allow_pickle=False) as arrays:
        for role, mask, geographic in (
            ("plot", "geographic_particle_map_mask", True),
            ("magnetic_plot", "magnetic_particle_map_mask", False),
            ("footpoint_plot", "footpoint_particle_map_mask", True),
        ):
            metadata = manifest.get(role)
            if metadata is not None:
                images.append(validate_image(metadata, int(np.count_nonzero(arrays[mask])), geographic=geographic, path_resolver=path_resolver))
    configured = manifest.get("configured_plots", [])
    for metadata, path in zip(configured, selection_files):
        with np.load(path, allow_pickle=False) as arrays:
            mask = arrays["mask"]
            image = validate_image(metadata, int(np.count_nonzero(mask)), geographic=(
                metadata.get("plot_type") != "time_availability" and metadata.get("coordinate_view") in ("geographic", "footpoint")
            ), path_resolver=path_resolver)
            image["checks"]["mask_boolean"] = mask.dtype == np.dtype(bool)
            image["checks"]["selected_values_finite"] = all(
                np.all(np.isfinite(arrays[key][mask])) for key in ("x", "y", "values")
            )
            image["passed"] = all(image["checks"].values())
            images.append(image)
    counts_match = len(configured) == len(selection_files)
    return {"passed": counts_match and bool(images) and all(row["passed"] for row in images),
            "configured_selection_count_matches": counts_match, "images": images}
