import json
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.data import load_measurements
from pcsuchai.pipeline import run_analysis
from pcsuchai.plot_config import load_plot_specs
from pcsuchai.saved_plot_validation import validate_saved_selections
from pcsuchai.scientific_comparison import _read_npz


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def native_filter_products(tmp_path_factory):
    directory = tmp_path_factory.mktemp("native-frozen-filters")
    profile = directory / "profile.json"
    profile.write_text(json.dumps({"plots": [
        {"name": "all", "calculate_centroid": True, "width_px": 300, "height_px": 180},
        {"name": "empty", "calculate_centroid": True, "coordinate_view": "footpoint", "particle_gt": 1e99,
         "include_times": [["2018-04-16T10:25:56Z", "2018-04-16T12:00:00Z"]],
         "exclude_times": [["2018-04-16T10:25:56Z", "2018-04-16T10:27:56Z"]],
         "mlt_sector": "night", "width_px": 300, "height_px": 180},
        {"name": "density", "plot_type": "time_availability", "variable": "electron_density_300k", "coordinate_view": "magnetic",
         "width_px": 300, "height_px": 180}]}))
    outputs = run_analysis(ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle", directory / "products",
                           orbit_backend="skyfield", magnetic_backend="apexpy", eop_path=ROOT / "data/eop/finals2000A.all",
                           limit=6, plot_config_path=profile)
    return (_read_npz(outputs.raw_products_npz), load_measurements(ROOT / "data/raw/langmuir-2018-2.csv").first(6),
            load_plot_specs(profile), json.loads(Path(outputs.manifest_json).read_text()), list(outputs.plot_selection_files))


def test_all_native_filter_arrays_and_empty_recipes_verified(native_filter_products):
    result = validate_saved_selections(*native_filter_products)
    assert result["passed"]
    assert len(result["recipes"]) == 3
    assert result["recipes"][1]["selected_count"] == 0
    assert set(result["recipes"][0]["field_checks"]) == {"mask", "x", "y", "values", "x_label", "y_label", "value_label", "scale"}


def test_changed_empty_decision_fails_even_if_axes_are_finite(native_filter_products, tmp_path):
    raw, measurements, specs, manifest, files = native_filter_products
    changed = _read_npz(files[1])
    changed["mask"][0] = True
    filename = tmp_path / "altered-selection.npz"
    np.savez_compressed(filename, **changed)
    result = validate_saved_selections(raw, measurements, specs, manifest, [files[0], filename, files[2]])
    assert not result["passed"]
    assert not result["recipes"][1]["field_checks"]["mask"]["passed"]


def test_relabelled_recipe_does_not_pass_unchanged_selection(native_filter_products):
    raw, measurements, specs, manifest, files = native_filter_products
    altered = json.loads(json.dumps(manifest))
    altered["configured_plots"][1]["spec"]["exclude_times"] = []
    result = validate_saved_selections(raw, measurements, specs, altered, files)
    assert not result["passed"]
    assert not result["recipes"][1]["recipe_matches_frozen_input"]


@pytest.mark.parametrize("index,key,value", [(0, "value_min", -1e99), (0, "points_rendered", True),
    (0, "particle_weighted_centroid", None), (1, "data_status", "available"),
    (2, "first_time_utc", "2018-01-01T00:00:00+00:00"), (2, "last_time_utc", None)])
def test_tampered_analysis_metadata_fails_native_product_audit(native_filter_products, index, key, value):
    raw, measurements, specs, manifest, files = native_filter_products
    altered = json.loads(json.dumps(manifest))
    altered["configured_plots"][index][key] = value
    result = validate_saved_selections(raw, measurements, specs, altered, files)
    assert not result["passed"]
    assert not result["recipes"][index]["analysis_metadata"]["passed"]


@pytest.mark.parametrize("key", ["latitude_deg", "longitude_deg", "total_particle_count"])
def test_numerically_changed_centroid_is_rejected(native_filter_products, key):
    raw, measurements, specs, manifest, files = native_filter_products
    altered = json.loads(json.dumps(manifest))
    altered["configured_plots"][0]["particle_weighted_centroid"][key] += 1
    result = validate_saved_selections(raw, measurements, specs, altered, files)
    assert not result["passed"]


def test_undefined_centroid_requires_explicit_null_fields(native_filter_products):
    raw, measurements, specs, manifest, files = native_filter_products
    altered = json.loads(json.dumps(manifest))
    del altered["configured_plots"][1]["particle_weighted_centroid"]["longitude_deg"]
    assert not validate_saved_selections(raw, measurements, specs, altered, files)["passed"]
