"""Native published regressions plus explicitly injected acceptance faults."""

import copy

import numpy as np

import pytest

import pcsuchai.magnetic.references as references
from pcsuchai.validation_reference import CRITERIA, reference_contract_version, required_criteria


@pytest.fixture(scope="module", params=["aacgmv2", "apexpy"])
def native_report(request):
    """Acquire real installed-library results; no mocked science or Pi claims."""

    report = references.validate_magnetic_reference_cases(request.param)
    assert report["status"] == "pass", report
    return report


def test_native_published_anchors_and_complete_production_outputs(native_report):
    definitions = references.load_reference_cases()
    assert references.audit_reference_report(native_report, definitions, native_report["backend"])
    assert len(native_report["anchors"]) == (12 if native_report["backend"] == "aacgmv2" else 7)
    assert len(native_report["production_bridges"]) == (7 if native_report["backend"] == "aacgmv2" else 5)
    assert native_report["native_files"]
    assert all(item["comparison"]["passed"] for item in native_report["anchors"] + native_report["production_bridges"])


@pytest.mark.parametrize("fault", ["anchor_value", "anchor_delta", "anchor_units", "version", "missing_anchor",
                                  "bridge_value", "bridge_units", "bridge_missing", "bridge_null_mask", "bridge_label",
                                  "bridge_invariant", "definition_tolerance", "native_hash", "missing_native", "raw_float_bytes",
                                  "refreshed_bits_and_deltas"])
def test_saved_raw_reference_faults_cannot_pass_by_copying_status(native_report, fault):
    """Mutate test-owned documents only; these failures are synthetic injections."""

    report = copy.deepcopy(native_report)
    if fault == "anchor_value":
        report["anchors"][0]["actual"][0] += 1
    elif fault == "anchor_delta":
        report["anchors"][0]["comparison"]["absolute_deltas"][0] = 0
    elif fault == "anchor_units":
        report["anchors"][0]["definition"]["units"][0] = "radian"
    elif fault == "version":
        report["version_actual"] = "999.0"
    elif fault == "missing_anchor":
        report["anchors"].pop()
    elif fault == "bridge_value":
        report["production_bridges"][0]["actual"][2] += 12
    elif fault == "bridge_units":
        report["production_bridges"][0]["units"][5] = "angular_residual_degree"
    elif fault == "bridge_missing":
        report["production_bridges"].pop()
    elif fault == "bridge_null_mask":
        report["production_bridges"][4]["actual"][0] = 0
    elif fault == "bridge_label":
        report["production_bridges"][0]["actual_coordinate_system"] = "wrong-model"
    elif fault == "bridge_invariant":
        report["production_bridges"][0]["invariants"]["checks"].pop("known_error_codes")
    elif fault == "definition_tolerance":
        report["definition"]["tolerance"]["atol"] = 100
    elif fault == "native_hash":
        report["native_files"][0]["sha256"] = "Z" * 64
    elif fault == "missing_native":
        report["native_files"] = []
    elif fault == "raw_float_bytes":
        report["anchors"][0]["actual_float64_little_endian_hex"] = "00" * 24
    elif fault == "refreshed_bits_and_deltas":
        anchor = report["anchors"][0]
        anchor["actual"][0] += 1
        anchor["actual_float64_little_endian_hex"] = references._raw_numbers(anchor["actual"])["float64_little_endian_hex"]
        recomputed = references._comparison(anchor["actual"], anchor["definition"]["expected"], report["definition"]["tolerance"])
        assert not recomputed["passed"] and references._verify_raw_numbers(anchor)
        anchor["comparison"] = {**recomputed, "passed": True}
    assert not references.audit_reference_report(report, references.load_reference_cases(), report["backend"])


def test_missing_backend_fails_closed_without_importing_other_backend(monkeypatch):
    """Synthetic import fault; the unrequested model remains independent."""

    calls = []

    def unavailable(name):
        """Record the requested import and simulate its absence."""
        calls.append(name)
        raise ImportError("injected missing dependency")

    monkeypatch.setattr(references.importlib, "import_module", unavailable)
    report = references.validate_magnetic_reference_cases("apexpy")
    assert report["status"] == "fail" and report["version_actual"] is None
    assert report["anchors"] == report["production_bridges"] == []
    assert calls == ["apexpy"]
    assert "injected missing dependency" in report["error"]


def test_production_corruption_fails_even_when_native_anchors_pass(monkeypatch):
    """Inject a plumbing error into the actual production factory return."""

    actual = references.convert_magnetic

    def wrong_units(*args):
        """Alter only returned geodetic height while keeping native anchors intact."""
        result = actual(*args)
        result.surface_altitude_km[result.error_codes == 0] += 1
        return result

    monkeypatch.setattr(references, "convert_magnetic", wrong_units)
    report = references.validate_magnetic_reference_cases("aacgmv2")
    assert all(item["comparison"]["passed"] for item in report["anchors"])
    assert report["status"] == "fail"
    assert any(not item["comparison"]["passed"] for item in report["production_bridges"])


@pytest.mark.parametrize("backend", ["apexpy", "aacgmv2"])
def test_combined_native_dispatch_is_checked_against_primitives(monkeypatch, backend):
    """Inject a combined-wrapper bug; published primitives remain unmodified."""

    module = references.importlib.import_module(backend)
    owner = module.Apex if backend == "apexpy" else module
    name = "convert" if backend == "apexpy" else "get_aacgm_coord"
    actual = getattr(owner, name)

    def broken_wrapper(*args, **kwargs):
        """Perturb only the combined public wrapper's returned latitude."""
        result = actual(*args, **kwargs)
        return (result[0] + 1, *result[1:])

    monkeypatch.setattr(owner, name, broken_wrapper)
    report = references.validate_magnetic_reference_cases(backend)
    assert all(item["comparison"]["passed"] for item in report["anchors"])
    assert report["status"] == "fail"
    assert any(not item["comparison"]["passed"] for item in report["production_bridges"])


def test_frozen_upstream_tolerances_keep_boundary_semantics():
    tolerance = references.load_reference_cases()["models"]["aacgmv2"]["tolerance"]
    assert references._comparison([0.000149], [0], tolerance)["passed"]
    assert not references._comparison([0.00015], [0], tolerance)["passed"]
    assert not references._comparison([True], [1], tolerance)["passed"]
    assert not references._comparison([None], [0], tolerance)["passed"]


def test_raw_reference_numbers_preserve_nonfinite_and_negative_zero_bits():
    values = np.array([np.nan, np.inf, -np.inf, -0.0], dtype="<f8")
    raw = references._raw_numbers(values)
    assert raw["values"] == [None, None, None, -0.0]
    assert bytes.fromhex(raw["float64_little_endian_hex"]) == values.tobytes()
    assert references._verify_raw_numbers({"actual": raw["values"],
                                          "actual_float64_little_endian_hex": raw["float64_little_endian_hex"]})


def test_archived_source_not_optional_version_flag_controls_new_gates():
    old = {"files": [{"path": "src/pcsuchai/full_validation.py"}]}
    assert reference_contract_version(old) == 1 and required_criteria(old) == CRITERIA
    for member in (references.CASE_SOURCE, references.MODULE_SOURCE):
        source = {"files": old["files"] + [{"path": member}]}
        assert reference_contract_version(source) == 2 and len(required_criteria(source)) == 15
    for malformed in (None, {}, {"files": []}, {"files": [None]}):
        assert reference_contract_version(malformed) == 2
