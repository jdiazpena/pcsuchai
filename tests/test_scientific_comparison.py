import json
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.pipeline import run_analysis
from pcsuchai.scientific_comparison import compare_array, compare_scientific_products, audit_raw_products


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def native_products(tmp_path_factory):
    directory = tmp_path_factory.mktemp("native-comparison")
    config = directory / "plots.json"
    config.write_text(json.dumps({"plots": [{"name": "geo", "width_px": 300, "height_px": 180}]}))
    outputs = run_analysis(ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle",
                           directory / "products", orbit_backend="skyfield", magnetic_backend="apexpy",
                           eop_path=ROOT / "data/eop/finals2000A.all", limit=6, plot_config_path=config)
    with np.load(outputs.raw_products_npz, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    with np.load(outputs.plot_selection_files[0], allow_pickle=False) as archive:
        selection = {key: archive[key] for key in archive.files}
    return outputs, arrays, selection


def saved(path, arrays):
    np.savez_compressed(path, **arrays)
    return path


def test_all_native_fields_and_recipe_are_compared(native_products):
    outputs, arrays, _selection = native_products
    result = compare_scientific_products(outputs.raw_products_npz, outputs.raw_products_npz,
                                         reference_selections=outputs.plot_selection_files,
                                         candidate_selections=outputs.plot_selection_files)
    assert result["passed"]
    assert len(result["fields"]) == len(arrays)
    assert {"tle_selection_indices", "tle_selection_offset_seconds", "orbit_latitude_deg",
            "magnetic_surface_latitude_deg", "measurement_electron_density_300k"} <= result["fields"].keys()
    assert result["configured_selections"][0]["passed"]
    json.dumps(result, allow_nan=False)


def test_trusted_nonfinite_values_preserved_exactly(native_products, tmp_path):
    _outputs, source, _selection = native_products
    first = {key: value.copy() for key, value in source.items()}
    first["measurement_plasma_current"][:3] = [np.nan, np.inf, -np.inf]
    second = {key: value.copy() for key, value in first.items()}
    reference = saved(tmp_path / "first.npz", first)
    candidate = saved(tmp_path / "second.npz", second)
    assert compare_scientific_products(reference, candidate)["passed"]
    second["measurement_plasma_current"][1] = -np.inf
    assert not compare_scientific_products(reference, saved(candidate, second))["passed"]


def test_trusted_measurements_never_get_coordinate_tolerance(native_products, tmp_path):
    outputs, source, _selection = native_products
    candidate = {key: value.copy() for key, value in source.items()}
    candidate["measurement_plasma_temperature"][0] += 1e-10
    result = compare_scientific_products(outputs.raw_products_npz, saved(tmp_path / "changed.npz", candidate))
    assert not result["passed"]
    assert not result["fields"]["measurement_plasma_temperature"]["passed"]


def test_orbit_coordinates_obey_frozen_tolerance(native_products, tmp_path):
    outputs, source, _selection = native_products
    candidate = {key: value.copy() for key, value in source.items()}
    candidate["orbit_latitude_deg"][0] += 5e-8
    path = saved(tmp_path / "changed.npz", candidate)
    assert compare_scientific_products(outputs.raw_products_npz, path)["passed"]
    candidate["orbit_latitude_deg"][0] += 1e-6
    result = compare_scientific_products(outputs.raw_products_npz, saved(path, candidate))
    assert not result["passed"] and not result["fields"]["orbit_latitude_deg"]["passed"]


def test_longitude_and_mlt_wrap_without_comparing_different_models(native_products, tmp_path):
    _outputs, source, _selection = native_products
    first = {key: value.copy() for key, value in source.items()}
    second = {key: value.copy() for key, value in source.items()}
    first["orbit_longitude_deg"][0], second["orbit_longitude_deg"][0] = 180.0, -180.0
    first["magnetic_local_time_hours"][0], second["magnetic_local_time_hours"][0] = 23.99999, 0.00001
    assert compare_scientific_products(saved(tmp_path / "first.npz", first), saved(tmp_path / "second.npz", second))["passed"]
    second["magnetic_coordinate_system"] = np.asarray("aacgm")
    result = compare_scientific_products(tmp_path / "first.npz", saved(tmp_path / "second.npz", second))
    assert not result["passed"]  # own-model definition audit rejects relabeling


def test_error_domain_masks_are_exact_not_hidden_by_coordinate_tolerance(native_products, tmp_path):
    outputs, source, _selection = native_products
    candidate = {key: value.copy() for key, value in source.items()}
    candidate["magnetic_error_codes"][1] = 1
    for key, value in candidate.items():
        if key.startswith("magnetic_") and value.shape == (6,) and value.dtype.kind == "f":
            value[1] = np.nan
    candidate["magnetic_particle_map_mask"][1] = candidate["footpoint_particle_map_mask"][1] = False
    assert audit_raw_products(candidate)["passed"]
    result = compare_scientific_products(outputs.raw_products_npz, saved(tmp_path / "changed.npz", candidate))
    assert not result["passed"]
    assert not result["fields"]["magnetic_error_codes"]["passed"]


def test_recipe_coordinate_tolerance_does_not_relax_selected_rows(native_products, tmp_path):
    outputs, source, original_selection = native_products
    candidate = {key: value.copy() for key, value in source.items()}
    selection = {key: value.copy() for key, value in original_selection.items()}
    candidate["orbit_longitude_deg"][0] += 5e-8
    selection["x"][0] += 5e-8
    path = saved(tmp_path / "candidate.npz", candidate)
    selected = saved(tmp_path / "candidate.selection.npz", selection)
    options = {"reference_selections": outputs.plot_selection_files, "candidate_selections": (selected,)}
    assert compare_scientific_products(outputs.raw_products_npz, path, **options)["passed"]
    selection["mask"][0] = not selection["mask"][0]
    saved(selected, selection)
    result = compare_scientific_products(outputs.raw_products_npz, path, **options)
    assert not result["passed"] and not result["configured_selections"][0]["fields"]["mask"]["passed"]


def test_subset_requires_frozen_exact_rows_and_keeps_recipe_alignment(native_products, tmp_path):
    outputs, source, original_selection = native_products
    positions = np.array([0, 2, 5])
    candidate = {key: value[positions] if value.shape == (6,) else value for key, value in source.items()}
    selection = {key: value[positions] if value.shape == (6,) else value for key, value in original_selection.items()}
    path = saved(tmp_path / "subset.npz", candidate)
    selected = saved(tmp_path / "subset.selection.npz", selection)
    assert not compare_scientific_products(outputs.raw_products_npz, path)["passed"]
    options = {"reference_selections": outputs.plot_selection_files, "candidate_selections": (selected,),
               "expected_source_rows": source["measurement_source_rows"][positions]}
    assert compare_scientific_products(outputs.raw_products_npz, path, **options)["passed"]
    options["expected_source_rows"] = options["expected_source_rows"][::-1]
    assert not compare_scientific_products(outputs.raw_products_npz, path, **options)["passed"]


def test_large_integer_identities_keep_precision_and_native_width_semantics():
    assert compare_array(np.array([2, 3], dtype=np.int64), np.array([2, 3], dtype=np.int32))["passed"]
    assert not compare_array(np.array([2**53 + 1], dtype=np.int64), np.array([2**53 + 2], dtype=np.int64))["passed"]
    assert not compare_array(np.array([2**53 + 1], dtype=np.int64), np.array([2**53 + 1], dtype=np.uint64))["passed"]
    assert not compare_array(np.array([1.0], dtype=np.float64), np.array([1.0], dtype=np.float32))["passed"]


def test_missing_or_wrong_units_are_not_mutually_validated(native_products, tmp_path):
    outputs, source, _selection = native_products
    candidate = {key: value.copy() for key, value in source.items()}
    candidate.pop("tle_selection_offset_seconds")
    result = compare_scientific_products(outputs.raw_products_npz, saved(tmp_path / "missing.npz", candidate))
    assert not result["passed"] and "tle_selection_offset_seconds" in result["audits"]["candidate"]["missing_fields"]
    wrong = {key: value.copy() for key, value in source.items()}
    wrong["magnetic_surface_altitude_km"][:] = 1.0
    path = saved(tmp_path / "wrong.npz", wrong)
    assert not compare_scientific_products(path, path)["passed"]


def test_overflow_differences_remain_strict_json_and_fail():
    result = compare_array(np.array([1e308]), np.array([-1e308]), exact=False, tolerance=1e-7)
    assert not result["passed"] and result["maximum_absolute_difference"] is None
    json.dumps(result, allow_nan=False)
