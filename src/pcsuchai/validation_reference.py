"""Full-data evidence and exact frozen-workload acceptance from saved products.

Reference validity is bound to the recorded experiment, not today's analyst
runtime. Hashes detect retained corruption; they do not authenticate a malicious
self-signed archive or imply absolute physical model truth. Native backends are
not rerun during projection/comparison, and their different magnetic models are
never treated as coordinate-equality alternatives.
"""

from __future__ import annotations

import json
import gzip
import tarfile
import time
from dataclasses import fields

import numpy as np

from .models import MagneticResult, OrbitResult
from .plot_config import PlotSpec, select_plot_data
from .saved_attempts import _json, validate_saved_products, verify_artifact
from .scientific_comparison import _read_npz, compare_scientific_arrays
from .workload import select_measurements
from .magnetic.references import CASE_SOURCE, MODULE_SOURCE, audit_reference_report, load_reference_cases


PAIRS = tuple(f"{orbit}-{magnetic}" for orbit in ("astropy", "skyfield") for magnetic in ("aacgmv2", "apexpy"))
CRITERIA = {"tle_integrity_and_coverage", "eop_coverage", "sgp4_reference_vector", "trusted_measurement_integrity", "orbit_validation"}
CRITERIA |= {f"magnetic_validation:{orbit}" for orbit in ("astropy", "skyfield")}
CRITERIA |= {f"complete_pipeline:{pair}" for pair in PAIRS}
CRITERIA |= {f"orbit_output_independent_of_magnetic_backend:{orbit}" for orbit in ("astropy", "skyfield")}
ARTIFACT_NAMES = {"positions_csv": "positions_csv", "magnetic_positions_csv": "magnetic_positions_csv",
                  "geographic_map": "particle_map_png", "magnetic_map": "magnetic_particle_map_png",
                  "footpoint_map": "footpoint_particle_map_png", "manifest": "manifest_json",
                  "benchmark": "benchmark_json", "raw_products": "raw_products_npz", "raw_benchmark_samples": "raw_benchmark_samples"}
COMMON_STAGES = {"load_measurements", "load_and_select_tles", "propagate_orbit", "convert_magnetic_coordinates",
                 "write_positions", "render_and_write_plot", "write_magnetic_positions", "render_and_write_magnetic_plot",
                 "render_and_write_footpoint_plot", "write_raw_scientific_products"}


def reference_contract_version(source: dict) -> int:
    """Derive required gates from the archived source, not a removable flag.

    Older, verified source snapshots retain their original thirteen gates.
    Either new reference source member requires version two and both new gates.
    """

    if not isinstance(source, dict) or not isinstance(source.get("files"), list) or not source["files"]:
        return 2  # Missing provenance must not silently downgrade new gates.
    if any(not isinstance(item, dict) or not isinstance(item.get("path"), str) for item in source["files"]):
        return 2
    members = {item["path"] for item in source["files"]}
    return 2 if {CASE_SOURCE, MODULE_SOURCE} & members else 1


def required_criteria(source: dict) -> set:
    """Keep legacy acceptance intact while requiring new source's full contract."""

    return CRITERIA | ({f"magnetic_reference_cases:{backend}" for backend in ("aacgmv2", "apexpy")}
                       if reference_contract_version(source) == 2 else set())


def _verify_reference_artifacts(certificate: dict, paths, definitions: dict | None) -> dict:
    """Recheck compressed raw anchors, fixed tolerances and labelled bridges."""

    if reference_contract_version(certificate.get("source")) == 1:
        return {"passed": True, "scope": "historical_source_predates_published_magnetic_reference_contract"}
    results = {}
    try:
        definitions = definitions if definitions is not None else load_reference_cases()
        if certificate.get("validation_contract_version") != 2:
            raise ValueError("new reference source requires validation contract version two")
        records = certificate["magnetic_reference_cases"]
        if not isinstance(records, dict) or records.keys() != {"aacgmv2", "apexpy"}:
            raise ValueError("reference artifacts lack exactly both magnetic models")
        from .saved_attempts import _json_text
        for backend, record in records.items():
            try:
                filename = verify_artifact(record, paths)
                with gzip.open(filename, "rt", encoding="utf-8") as stream:
                    report = _json_text(stream.read())
                results[backend] = {"passed": audit_reference_report(report, definitions, backend)}
            except (OSError, ValueError, TypeError, KeyError, EOFError, UnicodeError) as exc:
                results[backend] = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"passed": all(item["passed"] for item in results.values()), "models": results,
                "scope": definitions["scope"]}
    except (OSError, ValueError, TypeError, KeyError, EOFError, UnicodeError) as exc:
        return {"passed": False, "models": results, "error": f"{type(exc).__name__}: {exc}"}


def verify_certificate_artifacts(certificate: dict, paths, *, measurements=None, tles=None, specs=None,
                                 reference_definitions=None) -> dict:
    """Recheck every full pipeline's bytes, raw schema, source rows and images.

    Even a diagnostic limited certificate can have its retained bytes audited.
    The caller separately decides whether its source/runtime/settings/criteria
    establish a full-data reference. All four pairs are mandatory in this audit.
    """

    pipelines = certificate.get("pipelines", {}) if isinstance(certificate, dict) else None
    if not isinstance(pipelines, dict) or pipelines.keys() != set(PAIRS):
        return {"passed": False, "reason": "full validation lacks exactly the four backend pipelines", "pipelines": {}}
    reports = {}
    for pair in PAIRS:
        try:
            pipeline = pipelines[pair]
            artifacts = pipeline["artifacts"]
            if artifacts.keys() != set(ARTIFACT_NAMES) | {"configured_plots", "plot_selections"}:
                raise ValueError("certificate lacks required pipeline artifact records")
            record = {"observations": pipeline["manifest"]["observations"],
                      "artifacts": {target: artifacts[name] for name, target in ARTIFACT_NAMES.items()},
                      "configured_plot_artifacts": artifacts["configured_plots"], "plot_selection_artifacts": artifacts["plot_selections"]}
            result = validate_saved_products(record, paths, measurements=measurements, tles=tles, specs=specs)
            actual = _json(verify_artifact(artifacts["manifest"], paths))
            result["certificate_manifest_matches"] = actual == pipeline["manifest"]
            result["passed"] &= result["certificate_manifest_matches"]
            order = [stage["stage"] for stage in result["stage_records"]]
            result["stage_order_matches"] = order == pipeline.get("stage_order")
            required = COMMON_STAGES | {f"render_configured_plot:{image['spec']['name']}" for image in actual.get("configured_plots", [])}
            result["required_stages_in_orbit_then_magnetic_chain"] = required <= set(order) and order.index("propagate_orbit") < order.index("convert_magnetic_coordinates")
            result["passed"] &= result["stage_order_matches"] and result["required_stages_in_orbit_then_magnetic_chain"]
            if f"{actual.get('orbit_backend')}-{actual.get('magnetic_backend')}" != pair:
                raise ValueError("reference manifest backend does not match its pipeline key")
            reports[pair] = result
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            reports[pair] = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    references = _verify_reference_artifacts(certificate, paths, reference_definitions)
    return {"passed": all(result["passed"] for result in reports.values()) and references["passed"], "pipelines": reports,
            "magnetic_references": references,
            "scope": "retained_full_pipeline_artifacts_not_source_authentication_or_absolute_model_truth"}


def _canonical_specs(experiment: dict) -> tuple:
    """Interpret the verified archived canonical profile without executing code."""

    archive = experiment["paths"].resolve(experiment["state"]["source_snapshot"]["path"])
    with tarfile.open(archive, "r:gz") as handle:
        member = handle.getmember("configs/plots/archive-full.json")
        if not member.isfile():
            raise ValueError("canonical reference profile is not an archived regular file")
        with handle.extractfile(member) as stream:
            document = json.load(stream)
    if not isinstance(document, dict) or document.keys() != {"plots"} or not isinstance(document["plots"], list):
        raise ValueError("canonical archived profile is malformed")
    specs = tuple(PlotSpec.from_dict(item) for item in document["plots"])
    if len(specs) != 32 or len({spec.name for spec in specs}) != len(specs):
        raise ValueError("canonical archived profile lacks its 32 unique recipes")
    return specs


def load_full_reference(experiment: dict) -> dict:
    """Bind a full certificate to frozen inputs/source/runtime and actual bytes.

    Missing evidence returns unavailable. A present but inconsistent or corrupted
    certificate returns failed, without changing archived files or today's OS.
    Retained artifacts are streamed/rechecked one pipeline at a time; returned
    evidence retains paths, not all full-data arrays/profile copies in RAM.
    """

    state, paths = experiment["state"], experiment["paths"]
    reference = state.get("full_validation_certificate")
    if not reference:
        return {"status": "unavailable", "passed": False, "reason": "no archived full-data validation certificate"}
    if not experiment["provenance_available"] or experiment["measurements"] is None or experiment["tles"] is None:
        return {"status": "failed", "passed": False, "reason": "full reference lacks verified experiment provenance/snapshots"}
    try:
        filename = paths.resolve(reference)
        certificate = _json(filename)
        source_members = {item["path"]: item for item in state["source"]["files"]}
        needed = required_criteria(state["source"])
        checks = {
            "type": certificate.get("certificate_type") == "pcsuchai-full-code-validation",
            "schema": certificate.get("schema_version") == 1,
            "status": certificate.get("status") == "pass",
            "full_unlimited_canonical_workload": certificate.get("full_code_workload") is True and certificate.get("official_eligible") is True
                                                and certificate.get("settings", {}).get("limit") is None and certificate.get("settings", {}).get("plot_count") == 32,
            "source": certificate.get("source") == state["source"],
            "validation_contract_version": certificate.get("validation_contract_version", 1) == reference_contract_version(state["source"]),
            "python_version": certificate.get("runtime", {}).get("python_version") == state["runtime"].get("python_version"),
            "packages": certificate.get("runtime", {}).get("packages") == state["runtime"].get("packages"),
            "all_required_criteria": needed <= certificate.get("criteria", {}).keys() and all(
                certificate["criteria"][name].get("passed") is True for name in needed if name in certificate.get("criteria", {})),
            "all_recorded_criteria_pass": bool(certificate.get("criteria")) and all(
                isinstance(value, dict) and value.get("passed") is True for value in certificate.get("criteria", {}).values()),
            "canonical_plot_hash": certificate.get("inputs", {}).get("plot_config", {}).get("sha256") == source_members["configs/plots/archive-full.json"]["sha256"],
        }
        for name in ("measurements", "tle", "eop"):
            checks[f"input:{name}"] = all(certificate.get("inputs", {}).get(name, {}).get(key) == state["inputs"][name].get(key)
                                         for key in ("sha256", "size_bytes"))
        if not all(checks.values()):
            return {"status": "failed", "passed": False, "checks": checks, "reason": "archived full certificate does not match its experiment"}
        specs = _canonical_specs(experiment)
        definitions = None
        if reference_contract_version(state["source"]) == 2:
            from .saved_attempts import _json_text
            archive = paths.resolve(state["source_snapshot"]["path"])
            with tarfile.open(archive, "r:gz") as handle:
                member = handle.getmember(CASE_SOURCE)
                if not member.isfile():
                    raise ValueError("archived magnetic references are not a regular file")
                with handle.extractfile(member) as stream:
                    definitions = _json_text(stream.read().decode("utf-8"))
        audit = verify_certificate_artifacts(certificate, paths, measurements=experiment["measurements"], tles=experiment["tles"], specs=specs,
                                             reference_definitions=definitions)
        from .benchmark import sha256_file
        return {"status": "available" if audit["passed"] else "failed", "passed": audit["passed"],
                "certificate": str(filename), "certificate_sha256": sha256_file(filename), "checks": checks,
                "artifact_audit": {"passed": audit["passed"], "magnetic_references": audit["magnetic_references"], "pipelines": {pair: {"passed": result["passed"], "error": result.get("error")}
                                                                                    for pair, result in audit["pipelines"].items()}},
                "raw_products": {pair: result["raw_products"] for pair, result in audit["pipelines"].items() if result["passed"]},
                "scope": "archived_full_data_software_acceptance_and_integrity_not_absolute_satellite_or_magnetic_accuracy"}
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError, tarfile.TarError, EOFError) as exc:
        return {"status": "failed", "passed": False, "reason": f"{type(exc).__name__}: {exc}"}


class _ReferenceRecipes:
    """Sized lazy projection of the candidate profile on full reference arrays."""

    def __init__(self, specs, measurements, raw):
        """Retain one pair's full raw arrays, not 32 additional recipe copies."""

        self.specs, self.measurements = specs, measurements
        self.orbit = OrbitResult(**{item.name: raw[f"orbit_{item.name}"].item() if item.name == "backend" else raw[f"orbit_{item.name}"] for item in fields(OrbitResult)})
        self.magnetic = MagneticResult(**{item.name: raw[f"magnetic_{item.name}"].item() if item.name in ("backend", "coordinate_system") else raw[f"magnetic_{item.name}"] for item in fields(MagneticResult)})

    def __len__(self):
        """Expose the declared number of recipes, including valid empty filters."""

        return len(self.specs)

    def __getitem__(self, index):
        """Reconstruct one full-data recipe under the frozen filtering contract."""

        selected = select_plot_data(self.specs[index], self.measurements, self.orbit, self.magnetic)
        return {"mask": selected.mask, "x": selected.x, "y": selected.y, "values": selected.values,
                "x_label": np.asarray(selected.x_label), "y_label": np.asarray(selected.y_label),
                "value_label": np.asarray(selected.value_label), "scale": np.asarray(selected.scale)}


def accept_workload_variant(experiment: dict, reference: dict, block: dict, pair: str, products: dict) -> dict:
    """Check the first/every attempt against its own full-data pair and filters.

    Same-backend derived coordinates follow the frozen fidelity policy; trusted
    values, row/TLE identity, invalid/domain masks and plot decisions are exact.
    Explicit source-index selection projects the full reference to this workload.
    No equality between Apex/AACGM or different orbit backends is imposed here.
    """

    if not reference["passed"]:
        return {"status": reference["status"], "passed": False, "reason": reference.get("reason", "full reference artifact audit failed")}
    try:
        from .plot_config import load_plot_specs
        from .scientific_comparison import _SelectionFiles
        full = _read_npz(reference["raw_products"][pair])
        candidate = _read_npz(products["raw_products"])
        selected = select_measurements(experiment["measurements"], block["size"], block["selection_method"])
        profile = block["plot_profile"]
        specs = load_plot_specs(experiment["snapshot_validation"]["input_paths"][f"plot:{profile['name']}"]) if profile["config"] else ()
        comparison = compare_scientific_arrays(full, candidate, expected_source_rows=selected.source_rows,
                                               reference_selections=_ReferenceRecipes(specs, experiment["measurements"], full),
                                               candidate_selections=_SelectionFiles(products["selection_files"]),
                                               reference_label=reference["raw_products"][pair], candidate_label=products["raw_products"])
        return {"status": "accepted" if comparison["passed"] else "failed", "passed": comparison["passed"],
                "pair": pair, "selection": {"method": block["selection_method"], "size": block["size"]},
                "profile": profile["name"], "recipe_count": len(specs), "certificate_sha256": reference["certificate_sha256"],
                "comparison": comparison, "limit": "exact-workload software fidelity to accepted full data; not independent absolute model truth"}
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
        return {"status": "failed", "passed": False, "reason": f"{type(exc).__name__}: {exc}"}


def audit_experiment_workloads(experiment: dict, output_dir, *, reference: dict | None = None) -> dict:
    """Save every attempt's full-reference decision after measured clocks finish.

    Original run/checkpoint bytes are not modified. This scientific acceptance
    cost is explicitly separate from satellite-style worker/cycle latency. ALL
    failed/incomplete/excluded attempts remain in the journal/denominator; no
    retries are scheduled and no success is inferred from an empty inventory.
    """

    from pathlib import Path
    from .saved_attempts import iter_saved_attempts
    from .benchmark_suite import _atomic_write_json

    started, cpu_started = time.monotonic(), time.process_time()
    reference = load_full_reference(experiment) if reference is None else reference
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    blocks = {block["path"]: block for block in experiment["blocks"]}
    counts = {kind: {"started": 0, "accepted": 0, "failed": 0, "interrupted": 0, "excluded": 0, "unavailable": 0}
              for kind in ("measured", "warmup", "unknown")}
    with gzip.open(destination / "workload-acceptance.jsonl.gz", "xt", encoding="utf-8") as journal:
        for attempt in iter_saved_attempts(experiment):
            kind = attempt.get("kind")
            count = counts[kind if kind in ("measured", "warmup") else "unknown"]
            count["started"] += 1
            acceptance = {"status": "not_checked", "passed": False, "reason": "original attempt incomplete/excluded"}
            if kind in ("measured", "warmup") and attempt["block_path"] in blocks and attempt["status"] == "complete" and attempt["products"] is not None and not attempt["issues"]:
                acceptance = accept_workload_variant(experiment, reference, blocks[attempt["block_path"]], attempt["pair"], attempt["products"])
                if acceptance["passed"]:
                    count["accepted"] += 1
                elif acceptance["status"] == "unavailable":
                    count["unavailable"] += 1
                else:
                    count["failed"] += 1
            elif attempt["status"] == "interrupted":
                count["interrupted"] += 1
            elif attempt["status"] == "failed":
                count["failed"] += 1
            else:
                count["excluded"] += 1
            journal.write(json.dumps({"run_id": attempt["run_id"], "block_path": attempt["block_path"], "kind": attempt["kind"],
                                      "pair": attempt["pair"], "recorded_status": attempt["recorded_status"],
                                      "record_sha256": attempt["record_sha256"], "saved_product_issues": attempt["issues"],
                                      "acceptance": acceptance}, separators=(",", ":"), allow_nan=False) + "\n")
    measured = counts["measured"]
    summary = {"acceptance_schema_version": 1,
               "status": "accepted" if measured["started"] > 0 and measured["accepted"] == measured["started"]
                         and counts["warmup"]["accepted"] == counts["warmup"]["started"]
                         and not counts["unknown"]["started"] else "incomplete_or_failed",
               "attempt_counts": counts, "full_reference": reference,
               "wall_seconds": time.monotonic() - started, "process_cpu_seconds": time.process_time() - cpu_started,
               "timing_scope": "postmeasurement_scientific_acceptance_excluded_from_worker_and_measured_campaign_clocks",
               "journal": "workload-acceptance.jsonl.gz", "original_attempts_modified": False,
               "limit": "software scientific fidelity; not complete hardware/thermal/PMU acceptance"}
    _atomic_write_json(destination / "workload-acceptance.json", summary)
    return summary
