"""Native small-input reference fidelity; fixture timings are not Pi evidence."""

import copy
import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.benchmark import runtime_metadata, sha256_file
from pcsuchai.benchmark_suite import _source_digest, _validate_run
from pcsuchai.experiment import ExperimentManifest
from pcsuchai.experiment_runner import experiment_blocks, safe_name
from pcsuchai.full_validation import run_full_validation
from pcsuchai.pipeline import run_analysis
from pcsuchai.portable import PortablePaths
from pcsuchai.retention import snapshot_inputs, snapshot_sources
from pcsuchai.saved_attempts import saved_experiment, validate_saved_products
from pcsuchai.validation_reference import (
    accept_workload_variant, audit_experiment_workloads, load_full_reference,
    verify_certificate_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


@pytest.fixture(scope="module")
def full_reference(tmp_path_factory):
    """Actually validate ALL six fixture rows/four pairs/32 canonical recipes.

    Unlimited here means the entire frozen six-row input, not the 26,725-row
    canonical dataset. Production full-data evidence is retained separately.
    """

    root = tmp_path_factory.mktemp("native-full-reference")
    measurements = root / "small-source.csv"
    with (ROOT / "data/raw/langmuir-2018-2.csv").open() as stream:
        measurements.write_text("".join(next(stream) for _ in range(7)))
    profile = root / "candidate-profile.json"
    write_json(profile, {"plots": [
        {"name": "candidate-geographic", "width_px": 300, "height_px": 180},
        {"name": "candidate-footpoint", "coordinate_view": "footpoint", "width_px": 300, "height_px": 180},
        {"name": "candidate-empty", "particle_ge": 1000000000, "width_px": 300, "height_px": 180},
    ]})
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    data["workload"]["measurements"] = str(measurements)
    data["workload"]["pairs"] = ["skyfield-apexpy"]
    data["workload"]["selection"]["sizes"] = [2]
    data["workload"]["plot_profiles"] = [{"name": "custom", "config": str(profile)}]
    manifest = ExperimentManifest.from_dict(data)
    inputs = {"measurements": measurements, "tle": ROOT / data["workload"]["tle"],
              "eop": ROOT / data["workload"]["eop"], "plot:custom": profile}
    state = {"manifest": data, "manifest_sha256": manifest.sha256, "runtime": runtime_metadata(),
             "source": _source_digest(ROOT), "device_label": "local-native-small-fixture",
             "started_utc": "2026-09-15T00:00:00+00:00", "segments": [],
             "blocks": experiment_blocks(manifest), "status": "stopped",
             "inputs": {key: {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
                        for key, path in inputs.items()}}
    state["input_snapshots"] = snapshot_inputs(
        {f"{safe_name(key)}-{hashlib.sha256(key.encode()).hexdigest()[:8]}": path for key, path in inputs.items()}, root / "inputs")
    state["source_snapshot"] = snapshot_sources(ROOT, state["source"], root / "source-snapshot.tar.gz")
    certificate = run_full_validation(root / "validation", ROOT, measurements, inputs["tle"], inputs["eop"],
                                      ROOT / "configs/plots/archive-full.json")
    assert certificate["official_eligible"] and certificate["status"] == "pass"
    state["full_validation_certificate"] = str(Path(certificate["certificate_path"]).relative_to(root))
    write_json(root / "manifest.json", data)
    write_json(root / "experiment-state.json", state)
    experiment = saved_experiment(root)
    reference = load_full_reference(experiment)
    assert reference["passed"], reference
    return experiment, reference, certificate, inputs


@pytest.mark.parametrize("method,size", [("prefix", 2), ("spread", 2), ("spread", 1), ("full", None)])
def test_native_workload_projection_keeps_rows_and_different_frozen_recipes(full_reference, tmp_path, method, size):
    experiment, reference, _certificate, inputs = full_reference
    block = {**experiment["blocks"][0], "selection_method": method, "size": size}
    outputs = run_analysis(inputs["measurements"], inputs["tle"], tmp_path / "products",
                           orbit_backend="skyfield", magnetic_backend="apexpy", eop_path=inputs["eop"],
                           limit=size, selection_method=method, plot_config_path=inputs["plot:custom"], benchmark=True)
    record = _validate_run(asdict(outputs), 1.0)  # synthetic metadata, not a benchmark
    products = validate_saved_products(record, PortablePaths(tmp_path))
    assert products["passed"]
    result = accept_workload_variant(experiment, reference, block, "skyfield-apexpy", products)
    assert result["passed"], result
    assert result["recipe_count"] == 3
    assert all(item["passed"] for item in result["comparison"]["configured_selections"])


def test_first_wrong_attempt_fails_even_when_it_would_match_itself(full_reference, tmp_path):
    experiment, reference, _certificate, inputs = full_reference
    outputs = run_analysis(inputs["measurements"], inputs["tle"], tmp_path / "products",
                           orbit_backend="skyfield", magnetic_backend="apexpy", eop_path=inputs["eop"],
                           limit=2, benchmark=True)
    with np.load(outputs.raw_products_npz, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    arrays["orbit_latitude_deg"][0] += 1e-5  # valid domain, outside frozen same-backend tolerance
    np.savez_compressed(outputs.raw_products_npz, **arrays)
    # Refresh the byte hash, exactly the weakness of comparing repeat hashes only.
    record = _validate_run(asdict(outputs), 1.0)
    products = validate_saved_products(record, PortablePaths(tmp_path))
    assert products["passed"]
    block = {**experiment["blocks"][0], "plot_profile": {"name": "minimal", "config": None}}
    result = accept_workload_variant(experiment, reference, block, "skyfield-apexpy", products)
    assert not result["passed"]
    assert not result["comparison"]["fields"]["orbit_latitude_deg"]["passed"]


@pytest.mark.parametrize("change", ["limit", "criterion", "source", "input", "profile", "extra_failed_criterion", "missing_criterion", "official_flag",
                                  "missing_magnetic_reference", "missing_magnetic_gate", "contract_downgrade", "strip_new_contract"])
def test_present_inconsistent_certificate_is_failed_not_unavailable(full_reference, change):
    experiment, _reference, certificate, _inputs = full_reference
    candidate = copy.deepcopy(certificate)
    if change == "limit":
        candidate["settings"]["limit"] = 2
    elif change == "criterion":
        candidate["criteria"]["orbit_validation"]["passed"] = False
    elif change == "extra_failed_criterion":
        candidate["criteria"]["unexpected-failed-gate"] = {"passed": False}
    elif change == "missing_criterion":
        del candidate["criteria"]["orbit_validation"]
    elif change == "official_flag":
        candidate["official_eligible"] = False
    elif change == "missing_magnetic_reference":
        candidate.pop("magnetic_reference_cases")
    elif change == "missing_magnetic_gate":
        candidate["criteria"].pop("magnetic_reference_cases:apexpy")
    elif change == "contract_downgrade":
        candidate["validation_contract_version"] = 1
    elif change == "strip_new_contract":
        candidate.pop("validation_contract_version")
        candidate.pop("magnetic_reference_cases")
        for backend in ("aacgmv2", "apexpy"):
            candidate["criteria"].pop(f"magnetic_reference_cases:{backend}")
    elif change == "source":
        candidate["source"]["sha256"] = "0" * 64
    elif change == "input":
        candidate["inputs"]["tle"]["sha256"] = "0" * 64
    else:
        candidate["inputs"]["plot_config"]["sha256"] = "0" * 64
    path = experiment["root"] / f"test-owned-{change}-certificate.json"
    write_json(path, candidate)
    altered = {**experiment, "state": {**experiment["state"], "full_validation_certificate": path.name}}
    result = load_full_reference(altered)
    assert result["status"] == "failed" and not result["passed"]


def test_certificate_rechecks_artifacts_and_single_process_stage_order(full_reference):
    experiment, _reference, certificate, _inputs = full_reference
    corrupt = copy.deepcopy(certificate)
    corrupt["pipelines"]["astropy-apexpy"]["artifacts"]["raw_products"]["sha256"] = "0" * 64
    assert not verify_certificate_artifacts(corrupt, experiment["paths"])["passed"]
    reordered = copy.deepcopy(certificate)
    order = reordered["pipelines"]["skyfield-apexpy"]["stage_order"]
    first, second = order.index("propagate_orbit"), order.index("convert_magnetic_coordinates")
    order[first], order[second] = order[second], order[first]
    assert not verify_certificate_artifacts(reordered, experiment["paths"])["passed"]


def test_reference_artifact_bytes_and_raw_values_are_rechecked(full_reference):
    """Inject retained-byte and refreshed-hash faults into test-owned copies."""

    experiment, _reference, certificate, _inputs = full_reference
    corrupt = copy.deepcopy(certificate)
    corrupt["magnetic_reference_cases"]["aacgmv2"]["sha256"] = "0" * 64
    audit = verify_certificate_artifacts(corrupt, experiment["paths"])
    assert not audit["passed"] and not audit["magnetic_references"]["passed"]
    original = certificate["magnetic_reference_cases"]["apexpy"]
    with gzip.open(original["path"], "rt") as stream:
        report = json.load(stream)
    report["anchors"][0]["actual"][0] += 1
    target = experiment["root"] / "test-owned-invalid-reference.json.gz"
    with gzip.open(target, "wt") as stream:
        json.dump(report, stream)
    corrupt["magnetic_reference_cases"]["apexpy"] = {
        "path": str(target), "sha256": sha256_file(target), "size_bytes": target.stat().st_size}
    audit = verify_certificate_artifacts(corrupt, experiment["paths"])
    assert not audit["passed"] and not audit["magnetic_references"]["models"]["apexpy"]["passed"]


def test_repeated_full_validation_never_overwrites_retained_evidence(full_reference):
    """Reject a real repeated invocation before changing its complete products."""

    experiment, _reference, certificate, inputs = full_reference
    destination = Path(certificate["certificate_path"]).parent
    inventory = {path: sha256_file(path) for path in destination.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError, match="use a new dated directory"):
        run_full_validation(destination, ROOT, inputs["measurements"], inputs["tle"], inputs["eop"],
                            ROOT / "configs/plots/archive-full.json")
    assert inventory == {path: sha256_file(path) for path in destination.rglob("*") if path.is_file()}


@pytest.mark.parametrize("pipelines", [None, [], "not-an-object", {}])
def test_malformed_pipeline_inventory_returns_failed_evidence(tmp_path, pipelines):
    assert not verify_certificate_artifacts({"pipelines": pipelines}, PortablePaths(tmp_path))["passed"]


def test_runtime_certificate_verifier_rejects_failed_or_missing_criteria(full_reference):
    from pcsuchai.full_validation import verify_validation_certificate
    experiment, _reference, certificate, inputs = full_reference
    candidate = copy.deepcopy(certificate)
    candidate["criteria"]["orbit_validation"]["passed"] = False
    path = experiment["root"] / "test-owned-failed-runtime-certificate.json"
    write_json(path, candidate)
    result = verify_validation_certificate(path, ROOT, inputs["measurements"], inputs["tle"], inputs["eop"],
                                           ROOT / "configs/plots/archive-full.json", None)
    assert not result["passed"]
    assert not result["checks"]["all_recorded_criteria_pass"]
    del candidate["criteria"]["orbit_validation"]
    write_json(path, candidate)
    result = verify_validation_certificate(path, ROOT, inputs["measurements"], inputs["tle"], inputs["eop"],
                                           ROOT / "configs/plots/archive-full.json", None)
    assert not result["checks"]["all_required_criteria"]


def test_runtime_verifier_cannot_downgrade_contract_by_stripping_source_members(full_reference):
    """A copied source digest cannot stand in for the exact executable inventory."""

    from pcsuchai.full_validation import verify_validation_certificate
    from pcsuchai.magnetic.references import CASE_SOURCE, MODULE_SOURCE
    experiment, _reference, certificate, inputs = full_reference
    candidate = copy.deepcopy(certificate)
    candidate["source"]["files"] = [item for item in candidate["source"]["files"]
                                     if item["path"] not in (CASE_SOURCE, MODULE_SOURCE)]
    candidate.pop("validation_contract_version")
    candidate.pop("magnetic_reference_cases")
    for backend in ("aacgmv2", "apexpy"):
        candidate["criteria"].pop(f"magnetic_reference_cases:{backend}")
    path = experiment["root"] / "test-owned-source-downgrade.json"
    write_json(path, candidate)
    result = verify_validation_certificate(path, ROOT, inputs["measurements"], inputs["tle"], inputs["eop"],
                                           ROOT / "configs/plots/archive-full.json", None)
    assert not result["passed"]
    assert not result["checks"]["source"] and not result["checks"]["validation_contract_version"]
    assert not result["checks"]["all_required_criteria"]


@pytest.mark.parametrize("raw", ['[]', '{"status":"pass","status":"fail"}', '{"source":null}', '{broken'])
def test_runtime_certificate_verifier_rejects_malformed_json_without_throwing(tmp_path, raw):
    from pcsuchai.full_validation import verify_validation_certificate
    path = tmp_path / "bad.json"
    path.write_text(raw)
    result = verify_validation_certificate(path, ROOT, "unused", "unused", "unused", "unused", None)
    assert not result["passed"]


def test_empty_acceptance_inventory_cannot_pass_and_originals_are_immutable(full_reference, tmp_path):
    experiment, reference, _certificate, _inputs = full_reference
    before = {path: sha256_file(path) for path in experiment["root"].rglob("*") if path.is_file()}
    result = audit_experiment_workloads(experiment, tmp_path / "audit", reference=reference)
    assert result["status"] == "incomplete_or_failed"
    assert result["attempt_counts"]["measured"]["started"] == 0
    assert result["timing_scope"].startswith("postmeasurement_")
    assert before == {path: sha256_file(path) for path in experiment["root"].rglob("*") if path.is_file()}
    with gzip.open(tmp_path / "audit/workload-acceptance.jsonl.gz", "rt") as stream:
        assert list(stream) == []
    with pytest.raises(FileExistsError):
        audit_experiment_workloads(experiment, tmp_path / "audit", reference=reference)


@pytest.mark.parametrize("kind,status", [("unknown", "complete"), ("warmup", "failed"), ("measured", "interrupted")])
def test_audit_keeps_unknown_failed_warmup_and_partial_slots(tmp_path, monkeypatch, kind, status):
    """Synthetic accounting fault test; no manufactured scientific evidence."""

    import pcsuchai.saved_attempts as reader
    experiment = {"blocks": [{"path": "b"}]}
    base = {"run_id": "measured", "kind": "measured", "status": "complete", "recorded_status": "complete",
            "block_path": "b", "pair": "skyfield-apexpy", "products": {}, "issues": [], "record_sha256": "test"}
    fault = {**base, "run_id": "fault", "kind": kind, "status": status, "recorded_status": status}
    monkeypatch.setattr(reader, "iter_saved_attempts", lambda _experiment: iter([base, fault]))
    import pcsuchai.validation_reference as module
    monkeypatch.setattr(module, "accept_workload_variant", lambda *args: {"passed": True, "status": "accepted"})
    result = audit_experiment_workloads(experiment, tmp_path / "audit", reference={"passed": True})
    assert result["status"] == "incomplete_or_failed"
    assert result["attempt_counts"][kind]["started"] >= 1
    with gzip.open(tmp_path / "audit/workload-acceptance.jsonl.gz", "rt") as stream:
        assert len(list(stream)) == 2
