"""Acceptance gate for the complete production post-processing workload."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .benchmark import runtime_metadata, sha256_file
from .benchmark_suite import _source_digest
from .data import audit_measurements, load_measurements
from .orbit.integrity import audit_eop_coverage, validate_sgp4_reference_vector
from .pipeline import run_analysis
from .plot_config import load_plot_specs
from .symh import load_symh, plot_symh
from .tle import audit_tle_history
from .validation import validate_magnetic_backends, validate_orbit_backends


def _artifact(path: str | Path) -> dict:
    item = Path(path)
    return {"path": str(item), "size_bytes": item.stat().st_size, "sha256": sha256_file(item)}


def _criterion(passed: bool, detail: object) -> dict:
    return {"passed": bool(passed), "detail": detail}


def run_full_validation(
    output_dir: str | Path,
    project_root: str | Path,
    measurements_path: str | Path,
    tle_path: str | Path,
    eop_path: str | Path,
    plot_config_path: str | Path,
    symh_path: str | Path | None = None,
    limit: int | None = None,
) -> dict:
    """Execute and certify every production stage and backend combination."""

    destination = Path(output_dir).resolve()
    root = Path(project_root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    measurements_file = Path(measurements_path)
    tle_file = Path(tle_path)
    eop_file = Path(eop_path)
    plot_file = Path(plot_config_path)
    measurements = load_measurements(measurements_file).first(limit)
    plot_specs = load_plot_specs(plot_file)
    criteria = {}

    print("[full-validation] auditing TLE, EOP, and SGP4 reference", file=sys.stderr, flush=True)
    measurement_audit = audit_measurements(measurements)
    tle_audit = audit_tle_history(tle_file, measurements.times)
    eop_audit = audit_eop_coverage(eop_file, measurements.times)
    sgp4_reference = validate_sgp4_reference_vector()
    criteria["tle_integrity_and_coverage"] = _criterion(tle_audit["status"] == "pass", tle_audit["status"])
    criteria["eop_coverage"] = _criterion(eop_audit["status"] == "pass", eop_audit["status"])
    criteria["sgp4_reference_vector"] = _criterion(sgp4_reference["status"] == "pass", sgp4_reference["status"])
    criteria["trusted_measurement_integrity"] = _criterion(
        measurement_audit["status"] == "pass", measurement_audit["status"]
    )

    orbit_dir = destination / "orbit"
    print("[full-validation] validating Astropy and Skyfield orbit paths", file=sys.stderr, flush=True)
    orbit_validation = validate_orbit_backends(
        measurements_file, tle_file, eop_file, orbit_dir / "orbit-validation.json",
        limit=limit, benchmark_output_path=orbit_dir / "orbit-benchmark.json",
        differences_output_path=orbit_dir / "orbit-differences.csv",
        plots_output_dir=orbit_dir / "plots",
    )
    criteria["orbit_validation"] = _criterion(
        orbit_validation["consistency_status"] == "pass",
        orbit_validation["consistency_status"],
    )

    magnetic_validations = {}
    for orbit_backend in ("astropy", "skyfield"):
        print(f"[full-validation] validating magnetic models on {orbit_backend} orbit", file=sys.stderr, flush=True)
        magnetic_dir = destination / "magnetic" / orbit_backend
        result = validate_magnetic_backends(
            measurements_file, tle_file, eop_file, orbit_backend,
            magnetic_dir / "magnetic-validation.json",
            magnetic_dir / "magnetic-benchmark.json", limit=limit,
            differences_output_path=magnetic_dir / "magnetic-differences.csv",
        )
        magnetic_validations[orbit_backend] = result
        criteria[f"magnetic_validation:{orbit_backend}"] = _criterion(
            result["execution_status"] == "pass" and result["positions_compared"] > 0,
            {"execution_status": result["execution_status"], "positions_compared": result["positions_compared"]},
        )

    pipelines = {}
    required_common_stages = {
        "load_measurements", "load_and_select_tles", "propagate_orbit",
        "convert_magnetic_coordinates", "write_positions", "render_and_write_plot",
        "write_magnetic_positions", "render_and_write_magnetic_plot",
        "render_and_write_footpoint_plot",
    }
    for orbit_backend in ("astropy", "skyfield"):
        for magnetic_backend in ("aacgmv2", "apexpy"):
            name = f"{orbit_backend}-{magnetic_backend}"
            print(
                f"[full-validation] complete pipeline {name} with {len(plot_specs)} configured plots",
                file=sys.stderr, flush=True,
            )
            run_dir = destination / "pipelines" / name
            outputs = run_analysis(
                measurement_path=measurements_file, tle_path=tle_file, eop_path=eop_file,
                output_dir=run_dir, orbit_backend=orbit_backend,
                magnetic_backend=magnetic_backend, limit=limit,
                plot_config_path=plot_file, benchmark=True,
            )
            manifest = json.loads(Path(outputs.manifest_json).read_text(encoding="utf-8"))
            stages = json.loads(Path(outputs.benchmark_json).read_text(encoding="utf-8"))
            stage_names = [item["stage"] for item in stages]
            artifacts = {
                "positions_csv": _artifact(outputs.positions_csv),
                "magnetic_positions_csv": _artifact(outputs.magnetic_positions_csv),
                "geographic_map": _artifact(outputs.particle_map_png),
                "magnetic_map": _artifact(outputs.magnetic_particle_map_png),
                "footpoint_map": _artifact(outputs.footpoint_particle_map_png),
                "manifest": _artifact(outputs.manifest_json),
                "benchmark": _artifact(outputs.benchmark_json),
                "configured_plots": [_artifact(path) for path in outputs.configured_plot_files],
            }
            order_passed = (
                "propagate_orbit" in stage_names and "convert_magnetic_coordinates" in stage_names
                and stage_names.index("propagate_orbit") < stage_names.index("convert_magnetic_coordinates")
            )
            configured_stages = {f"render_configured_plot:{spec.name}" for spec in plot_specs}
            stage_passed = required_common_stages.issubset(stage_names) and configured_stages.issubset(stage_names)
            plots_passed = len(outputs.configured_plot_files) == len(plot_specs) and all(
                item["size_bytes"] > 0 for item in artifacts["configured_plots"]
            )
            expected_magnetic_minimum = (
                len(measurements) if magnetic_backend == "apexpy"
                else int(np.floor(0.95 * len(measurements)))
            )
            validity_passed = (
                manifest["valid_positions"] == len(measurements)
                and manifest["valid_magnetic_positions"] >= expected_magnetic_minimum
            )
            pipelines[name] = {
                "manifest": manifest, "stage_order": stage_names, "artifacts": artifacts,
                "criteria": {
                    "single_process_order": order_passed,
                    "all_required_stages": stage_passed,
                    "all_configured_plots": plots_passed,
                    "valid_scientific_positions": validity_passed,
                },
            }
            criteria[f"complete_pipeline:{name}"] = _criterion(
                order_passed and stage_passed and plots_passed and validity_passed,
                pipelines[name]["criteria"],
            )

    for orbit_backend in ("astropy", "skyfield"):
        first = pipelines[f"{orbit_backend}-aacgmv2"]["artifacts"]["positions_csv"]["sha256"]
        second = pipelines[f"{orbit_backend}-apexpy"]["artifacts"]["positions_csv"]["sha256"]
        criteria[f"orbit_output_independent_of_magnetic_backend:{orbit_backend}"] = _criterion(
            first == second, {"aacgmv2_sha256": first, "apexpy_sha256": second},
        )

    symh_result = None
    if symh_path is not None:
        print("[full-validation] validating optional SYM-H processing", file=sys.stderr, flush=True)
        symh_times, symh_values = load_symh(symh_path)
        symh_result = plot_symh(symh_times, symh_values, destination / "external" / "symh.png")
        symh_result["input"] = _artifact(symh_path)
        symh_result["output"] = _artifact(symh_result["path"])
        criteria["optional_symh_processing"] = _criterion(
            symh_result["points_rendered"] > 0 and symh_result["output"]["size_bytes"] > 0,
            {"points": symh_result["points_rendered"]},
        )

    inputs = {
        "measurements": _artifact(measurements_file), "tle": _artifact(tle_file),
        "eop": _artifact(eop_file), "plot_config": _artifact(plot_file),
    }
    if symh_path is not None:
        inputs["symh"] = _artifact(symh_path)
    status = "pass" if all(item["passed"] for item in criteria.values()) else "fail"
    canonical_plot_file = root / "configs/plots/archive-full.json"
    canonical_plot_match = (
        canonical_plot_file.is_file()
        and sha256_file(plot_file) == sha256_file(canonical_plot_file)
        and len(plot_specs) == 32
    )
    official_eligible = status == "pass" and limit is None and canonical_plot_match
    report = {
        "schema_version": 1, "certificate_type": "pcsuchai-full-code-validation",
        "created_utc": datetime.now(timezone.utc).isoformat(), "status": status,
        "full_code_workload": official_eligible,
        "official_eligible": official_eligible,
        "official_eligibility": {
            "validation_passed": status == "pass", "unlimited_data": limit is None,
            "canonical_32_plot_profile": canonical_plot_match,
        },
        "project_root": str(root),
        "settings": {"limit": limit, "plot_count": len(plot_specs), "plot_config": str(plot_file)},
        "runtime": runtime_metadata(), "source": _source_digest(root), "inputs": inputs,
        "criteria": criteria, "measurement_audit": measurement_audit,
        "tle_audit": tle_audit, "eop_audit": eop_audit,
        "sgp4_reference_vector": sgp4_reference, "orbit_validation": orbit_validation,
        "magnetic_validations": magnetic_validations, "pipelines": pipelines,
        "symh": symh_result,
    }
    certificate_path = destination / "full-validation-certificate.json"
    certificate_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[full-validation] {status}: {certificate_path}", file=sys.stderr, flush=True)
    report["certificate_path"] = str(certificate_path)
    return report


def verify_validation_certificate(
    certificate_path: str | Path,
    project_root: str | Path,
    measurements: str | Path,
    tle: str | Path,
    eop: str | Path,
    plot_config: str | Path,
    limit: int | None,
) -> dict:
    """Require a passing certificate for the exact code, inputs, and runtime."""

    certificate = json.loads(Path(certificate_path).read_text(encoding="utf-8"))
    current_runtime = runtime_metadata()
    expected_inputs = {
        "measurements": sha256_file(measurements), "tle": sha256_file(tle),
        "eop": sha256_file(eop), "plot_config": sha256_file(plot_config),
    }
    checks = {
        "certificate_type": certificate.get("certificate_type") == "pcsuchai-full-code-validation",
        "status": certificate.get("status") == "pass",
        "full_code_workload": certificate.get("full_code_workload") is True,
        "source": certificate.get("source", {}).get("sha256") == _source_digest(Path(project_root).resolve())["sha256"],
        "python_version": certificate.get("runtime", {}).get("python_version") == current_runtime["python_version"],
        "packages": certificate.get("runtime", {}).get("packages") == current_runtime["packages"],
        "limit": certificate.get("settings", {}).get("limit") == limit,
        "plot_count": certificate.get("settings", {}).get("plot_count") == len(load_plot_specs(plot_config)),
        **{
            f"input:{name}": certificate.get("inputs", {}).get(name, {}).get("sha256") == digest
            for name, digest in expected_inputs.items()
        },
    }
    return {"passed": all(checks.values()), "checks": checks, "certificate": str(certificate_path)}
