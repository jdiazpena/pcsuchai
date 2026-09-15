"""Reconstruct complete filter decisions from frozen recipes and saved arrays.

The version-2 verifier interprets declared options and analysis metadata, without executing archived
code, recomputing an orbit or importing either native magnetic backend. This
checks that the arrays actually plotted obey all recorded filtering options.
"""

from __future__ import annotations

import json
from dataclasses import fields

import numpy as np

from .models import MagneticResult, OrbitResult
from .plot_config import plot_spec_metadata, select_plot_data
from .scientific_comparison import _read_npz, compare_array
from .analysis_validation import validate_analysis_metadata


def validate_saved_selections(raw: dict, measurements, specs: tuple, manifest: dict,
                              selection_files: list) -> dict:
    """Verify every recipe, mask, axis/value/scale and observation identity.

    Masks and own-file plot values are exact; this is distinct from tolerant
    cross-platform comparison of derived coordinates. Empty selections are
    legitimate and stay empty. Extra/missing/reordered recipes fail validation.
    """

    metadata = manifest.get("configured_plots", [])
    if len(specs) != len(selection_files) or len(specs) != len(metadata):
        return {"passed": False, "reason": "frozen configured recipe/image/selection counts differ", "verifier_version": 2}
    orbit = OrbitResult(**{item.name: raw[f"orbit_{item.name}"].item() if item.name == "backend" else raw[f"orbit_{item.name}"] for item in fields(OrbitResult)})
    magnetic = MagneticResult(**{item.name: raw[f"magnetic_{item.name}"].item() if item.name in ("backend", "coordinate_system") else raw[f"magnetic_{item.name}"] for item in fields(MagneticResult)})
    recipes = []
    for spec, image, filename in zip(specs, metadata, selection_files):
        expected = select_plot_data(spec, measurements, orbit, magnetic)
        arrays = _read_npz(filename)
        values = {"mask": expected.mask, "x": expected.x, "y": expected.y, "values": expected.values,
                  "x_label": np.asarray(expected.x_label), "y_label": np.asarray(expected.y_label),
                  "value_label": np.asarray(expected.value_label), "scale": np.asarray(expected.scale)}
        checks = {key: compare_array(value, arrays[key]) for key, value in values.items() if key in arrays}
        recipe_matches = json.dumps(image.get("spec"), sort_keys=True) == json.dumps(plot_spec_metadata(spec), sort_keys=True)
        analysis = validate_analysis_metadata(spec, expected, measurements, image)
        recipes.append({"name": spec.name, "recipe_matches_frozen_input": recipe_matches,
                        "selected_count": int(np.count_nonzero(expected.mask)), "field_checks": checks,
                        "analysis_metadata": analysis,
                        "passed": values.keys() == arrays.keys() and recipe_matches and analysis["passed"] and all(check["passed"] for check in checks.values())})
    return {"passed": all(recipe["passed"] for recipe in recipes), "recipes": recipes, "verifier_version": 2,
            "scope": "all_frozen_recipes_and_exact_own_file_plot_decisions_not_independent_orbit_or_model_truth"}
