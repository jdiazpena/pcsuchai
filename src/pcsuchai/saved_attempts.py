"""Read immutable attempts, including failures/orphans, without rerunning science.

Checkpoints are scheduling evidence, not an exhaustive inventory: abrupt exits
can leave directories that were never indexed. Readers retain those slots and
classify corruption explicitly. Imported paths never fall back to the original
machine. This module does not modify, reconcile or retry any saved attempt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tarfile
from pathlib import Path

from .experiment import ExperimentManifest
from .experiment_runner import experiment_blocks
from .portable import PortablePaths


def _json(path: Path) -> dict:
    """Require an object and reject non-standard JSON NaN/infinity literals."""

    return _json_text(path.read_text(), str(path))


def _json_text(text: str, label: str = "saved raw document") -> dict:
    """Parse already acquired bytes/text without rereading a mutable pathname."""

    def invalid(value):
        raise ValueError(f"non-finite JSON literal {value}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def finite(raw):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value

    result = json.loads(text, parse_constant=invalid, object_pairs_hook=unique, parse_float=finite)
    if not isinstance(result, dict):
        raise ValueError(f"expected JSON object: {label}")
    return result


def _digest(value) -> str:
    """Hash canonical comparison settings without file paths or NaN coercion."""

    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _duration(value) -> float | None:
    """Missing/negative/non-finite/bool durations are unavailable, never zero."""

    return float(value) if type(value) in (int, float) and math.isfinite(value) and value > 0 else None


def saved_experiment(directory: str | Path) -> dict:
    """Read frozen scheduling/provenance and note missing or stale root state.

    A valid manifest still permits inventory when its state is torn. That
    inventory cannot enter a controlled comparison without source/input/runtime
    evidence. A live process is checked independently of the recorded status.
    """

    from .experiment_control import identity_is_live

    root = Path(directory).resolve()
    manifest = ExperimentManifest.load(root / "manifest.json")
    issues = []
    try:
        state = _json(root / "experiment-state.json")
    except (OSError, ValueError) as exc:
        state = {}
        issues.append(f"root state unavailable: {type(exc).__name__}: {exc}")
    if state.get("manifest_sha256") != manifest.sha256 or state.get("manifest") != manifest.data:
        issues.append("root state does not match the frozen manifest")
    paths = PortablePaths(root)
    blocks = experiment_blocks(manifest)
    expected = {block["path"] for block in blocks}
    actual = {path.relative_to(root).as_posix() for path in root.glob("sessions/session-*/block-*") if path.is_dir()}
    issues.extend(f"unrecognized retained block: {path}" for path in sorted(actual - expected))
    runtime = state.get("runtime", {})
    inputs = state.get("inputs", {})
    source = state.get("source", {})
    provenance_available = (isinstance(runtime, dict) and isinstance(inputs, dict) and isinstance(source, dict)
                            and isinstance(runtime.get("python_version"), str) and isinstance(runtime.get("packages"), dict)
                            and isinstance(source.get("sha256"), str) and len(source["sha256"]) == 64
                            and all(key in inputs and isinstance(inputs[key], dict) and inputs[key].get("sha256")
                                    for key in ("measurements", "tle", "eop")))
    if not provenance_available:
        issues.append("source/input/runtime provenance unavailable or malformed")
    snapshots, measurements, tles = None, None, None
    if provenance_available:
        try:
            from .snapshot_validation import verify_snapshots
            from .data import load_measurements
            from .tle import load_tle_history
            snapshots = verify_snapshots(state, paths)
            measurements = load_measurements(snapshots["input_paths"]["measurements"])
            tles = load_tle_history(snapshots["input_paths"]["tle"])
        except (OSError, ValueError, KeyError, TypeError, EOFError, AttributeError, tarfile.TarError) as exc:
            issues.append(f"frozen snapshots unavailable/invalid: {type(exc).__name__}: {exc}")
    identity = {"manifest_sha256": manifest.sha256, "source_sha256": source.get("sha256") if isinstance(source, dict) else None,
                "device_label": state.get("device_label"), "started_utc": state.get("started_utc"),
                "original_root": str(paths.original_root)}
    segment = (state.get("segments") or [{}])[-1]
    return {"root": root, "paths": paths, "manifest": manifest.data, "state": state,
            "blocks": blocks, "issues": issues, "provenance_available": provenance_available and not issues,
            "snapshot_validation": snapshots, "measurements": measurements, "tles": tles,
            "identity": _digest(identity), "live": identity_is_live(segment.get("identity", {}))}


def controlled_settings(experiment: dict, block: dict) -> dict:
    """Separate board-plus-software identity from frozen work/measurement controls.

    OS/ABI/kernel/architecture are reported system differences, not isolated
    silicon controls. Python/library drift remains a separate software cohort.
    Device labels, source paths, session counts and ordering seeds are not work.
    Full source/input hashes, filters, thread/process/cache/thermal/observation
    policies are controlled. No missing provenance is promoted to equivalence.
    """

    data, state = experiment["manifest"], experiment["state"]
    runtime = state.get("runtime", {})
    profile = block["plot_profile"]
    execution = {key: value for key, value in data["execution"].items() if key != "seed"}
    inputs = state.get("inputs", {})
    return {
        "source_sha256": state.get("source", {}).get("sha256"),
        "inputs": {key: {field: record.get(field) for field in ("sha256", "size_bytes")}
                   for key, record in sorted(inputs.items()) if isinstance(record, dict)},
        "python_version": runtime.get("python_version"), "packages": runtime.get("packages"),
        "launch_observation_declaration": runtime.get("launch_observation_declaration"),
        "kind": data["kind"], "execution": execution, "thermal": data["thermal"],
        "selection": {"method": block["selection_method"], "size": block["size"]},
        "plot_profile": {"name": profile["name"], "input_sha256": inputs.get(f"plot:{profile['name']}", {}).get("sha256")},
        "observation": {**data["observation"], "levels": [block["observation_level"]], "counter_groups": [block["counter_group"]]},
        "retention": data["retention"], "validation": data["validation"],
        "cpu_governor": runtime.get("cpu_governor"),
    }


def verify_artifact(artifact: dict, paths: PortablePaths) -> Path:
    """Verify a retained byte record through its internal portable reference."""

    from .benchmark import sha256_file

    path = paths.resolve(artifact["path"])
    if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or sha256_file(path) != artifact["sha256"]:
        raise ValueError(f"retained artifact integrity failed: {artifact.get('path')}")
    return path


def validate_saved_products(record: dict, paths: PortablePaths, *, measurements=None, tles=None, specs=None, expected_block=None) -> dict:
    """Recheck every declared byte, all row/domain masks and decoded images.

    This is retained-product integrity and own-model invariants, not independent
    absolute science or same-work cross-board acceptance. No orbit/magnetic
    calculation or archived executable is run while constructing this report.
    """

    from .product_validation import validate_pipeline_images
    from .scientific_comparison import _read_npz, audit_raw_products, compare_array
    from dataclasses import fields
    import numpy as np

    artifacts = record.get("artifacts", {})
    required = {"manifest_json", "positions_csv", "magnetic_positions_csv", "particle_map_png",
                "magnetic_particle_map_png", "footpoint_particle_map_png", "raw_products_npz", "benchmark_json"}
    if not isinstance(artifacts, dict) or not required <= artifacts.keys():
        raise ValueError("complete attempt is missing required artifact records")
    resolved = {key: verify_artifact(value, paths) for key, value in artifacts.items()}
    configured = [verify_artifact(value, paths) for value in record.get("configured_plot_artifacts", [])]
    selections = [verify_artifact(value, paths) for value in record.get("plot_selection_artifacts", [])]
    if len(configured) != len(selections):
        raise ValueError("configured plots and raw selections differ in count")
    manifest = _json(resolved["manifest_json"])
    image_bindings = {"plot": "particle_map_png", "magnetic_plot": "magnetic_particle_map_png", "footpoint_plot": "footpoint_particle_map_png"}
    for role, artifact in image_bindings.items():
        if not isinstance(manifest.get(role), dict) or paths.resolve(manifest[role]["path"]) != resolved[artifact]:
            raise ValueError("required map metadata does not bind its retained image")
    if paths.resolve(manifest["raw_products_npz"]) != resolved["raw_products_npz"]:
        raise ValueError("manifest raw-products reference differs from its retained artifact")
    if manifest.get("instrumentation", {}).get("level") != "minimal" and "raw_benchmark_samples" not in artifacts:
        raise ValueError("non-minimal attempt lacks retained raw stage samples")
    raw = _read_npz(resolved["raw_products_npz"])
    audit = audit_raw_products(raw)
    images = validate_pipeline_images(manifest, resolved["raw_products_npz"], tuple(selections), path_resolver=paths.resolve)
    binding = {"status": "unavailable", "reason": "no verified selected input snapshot supplied", "passed": False}
    if measurements is not None and tles is not None:
        from .tle import select_nearest_tles
        checks = {}
        for item in fields(measurements):
            value = getattr(measurements, item.name)
            expected = np.asarray([instant.isoformat() for instant in value]) if item.name == "times" else np.asarray(value)
            checks[f"measurement_{item.name}"] = compare_array(expected, raw[f"measurement_{item.name}"])
        selection = select_nearest_tles(measurements.times, tles)
        for item in fields(selection):
            checks[f"tle_selection_{item.name}"] = compare_array(getattr(selection, item.name), raw[f"tle_selection_{item.name}"])
        binding = {"status": "available", "passed": all(check["passed"] for check in checks.values()), "fields": checks,
                   "scope": "exact trusted rows/fields and nearest historical TLE assignments including future epochs"}
    row_count_matches = (type(manifest.get("observations")) is int and type(record.get("observations")) is int
                         and audit.get("rows") == manifest.get("observations") == record.get("observations"))
    variant_checks = {}
    if expected_block is not None:
        selection = manifest.get("workload_selection", {})
        variant_checks = {"observation_level": manifest.get("instrumentation", {}).get("level") == expected_block["observation_level"],
                          "selection_method": selection.get("method") == expected_block["selection_method"],
                          "selection_size": selection.get("requested_size") == expected_block["size"],
                          "backend_pair": f"{manifest.get('orbit_backend')}-{manifest.get('magnetic_backend')}" in expected_block["pairs"]}
    plots = {"passed": False, "status": "unavailable", "reason": "no verified frozen profile/selected measurements supplied"}
    if specs is not None and measurements is not None:
        from .saved_plot_validation import validate_saved_selections
        plots = validate_saved_selections(raw, measurements, specs, manifest, selections)
    stages = json.loads(resolved["benchmark_json"].read_text())
    if not isinstance(stages, list) or any(not isinstance(stage, dict) or not isinstance(stage.get("stage"), str) for stage in stages):
        raise ValueError("retained stage product has malformed records")
    # Preserve the verified plotting contract for output-scaling analysis.
    # Paths are rebased/bound above; recipes and geographic context stay intact.
    plot_products = [{"name": role, **{key: value for key, value in manifest[role].items() if key != "path"}}
                     for role in image_bindings]
    plot_products.extend({"name": item.get("spec", {}).get("name", f"configured-{index}"),
                          **{key: value for key, value in item.items() if key != "path"}}
                         for index, item in enumerate(manifest.get("configured_plots", []), 1))
    for plot_product, image in zip(plot_products, images["images"]):
        reported_size = plot_product.get("size_bytes")
        actual_size = Path(image["resolved_path"]).stat().st_size if image["passed"] else None
        plot_product.update(metadata_size_bytes=reported_size, size_bytes=actual_size,
                            size_source="stat of bound/hash-verified readable PNG" if actual_size is not None else "unavailable_invalid_image",
                            metadata_size_matches_file=type(reported_size) is int and reported_size == actual_size)
    selection_description = {key: value for key, value in manifest.get("workload_selection", {}).items() if key != "source_rows"}
    workload_details = {"observed_rows": audit["rows"], "selection": selection_description,
                        "plot_products": plot_products,
                        "source_row_identity": "exact measurement_source_rows in verified raw_products NPZ; never replaced by prefix guesses"}
    return {"passed": audit["passed"] and images["passed"] and row_count_matches and all(variant_checks.values())
            and (binding["passed"] if measurements is not None else True) and (plots["passed"] if specs is not None and measurements is not None else True),
            "raw_audit": audit, "images": images, "input_binding": binding, "row_count_matches": row_count_matches,
            "frozen_variant_checks": variant_checks, "plot_filter_validation": plots,
            "stage_records": stages,
            "workload_details": workload_details,
            "raw_products": str(resolved["raw_products_npz"]), "selection_files": [str(path) for path in selections],
            "scope": "retained_bytes_domain_masks_and_decoded_images_not_full_absolute_acceptance"}


def iter_saved_attempts(experiment: dict):
    """Yield every dated attempt, without trusting final-summary run lists.

    Reconciliation sidecars override status only after binding their original
    bytes. Partial attempts consume their identifiable slots. Duplicate/out-of-
    schedule slots remain visible but excluded; nothing is silently retried.
    Warm-ups have identities and outcomes but never enter primary latency means.
    """

    from .benchmark import sha256_file

    root, paths = experiment["root"], experiment["paths"]
    blocks = {block["path"]: block for block in experiment["blocks"]}
    directories = sorted(root.glob("sessions/session-*/block-*"))
    for block_dir in directories:
        if not block_dir.is_dir():
            continue
        if block_dir.is_symlink() or not block_dir.resolve().is_relative_to(root):
            raise ValueError(f"unsafe retained block directory: {block_dir}")
        block_path = block_dir.relative_to(root).as_posix()
        block = blocks.get(block_path)
        expected_measurements = None
        specs = None
        if block is not None and experiment["measurements"] is not None and experiment["tles"] is not None:
            from .workload import select_measurements
            expected_measurements = select_measurements(experiment["measurements"], block["size"], block["selection_method"])
            from .plot_config import load_plot_specs
            specs = load_plot_specs(experiment["snapshot_validation"]["input_paths"][f"plot:{block['plot_profile']['name']}"]) if block["plot_profile"]["config"] else ()
        block_info = block or {"path": block_path, "id": block_dir.name, "session_index": None,
                               "position": None, "pairs": [], "size": None, "selection_method": None,
                               "observation_level": None, "counter_group": None, "plot_profile": {"name": None, "config": None}}
        execution = {}
        checkpoint_errors = []
        for name in ("benchmark-session.checkpoint.json", "benchmark-session.json"):
            filename = block_dir / name
            if filename.is_file():
                try:
                    for item in _json(filename).get("execution_order", []):
                        execution.setdefault(item["run_id"], item)
                except (ValueError, KeyError, TypeError) as exc:
                    checkpoint_errors.append(f"{name}: {type(exc).__name__}: {exc}")
        slot_directories = {}
        for category in ("runs", "warmups"):
            for path in sorted((block_dir / category).glob("*/*")):
                match = re.search(r"-r(\d+)-(.+)$", path.name)
                if path.is_dir() and match:
                    slot_directories.setdefault((category, int(match[1]), match[2]), []).append(path.name)
        occupied = {}
        for category, kind in (("runs", "measured"), ("warmups", "warmup")):
            for run_dir in sorted((block_dir / category).glob("*/*")):
                if not run_dir.is_dir():
                    continue
                if run_dir.is_symlink() or not run_dir.resolve().is_relative_to(root) or any(
                        (run_dir / name).is_symlink() for name in ("attempt-intent.json", "run-record.json", "reconciliation-record.json", "cycle-timing.json", "child-timing.json")):
                    raise ValueError(f"unsafe retained attempt path: {run_dir}")
                issues = list(checkpoint_errors)
                match = re.search(r"-r(\d+)-(.+)$", run_dir.name)
                number, pair = (int(match[1]), match[2]) if match else (None, None)
                if block is None or match is None or pair not in block_info["pairs"]:
                    issues.append("unknown block or attempt identity")
                stop = experiment["manifest"]["execution"]["stop"]
                maximum = experiment["manifest"]["execution"]["warmups"] if kind == "warmup" else stop["value"] if stop["kind"] == "attempts_per_pair" else None
                if number is None or number < 1 or (maximum is not None and number > maximum):
                    issues.append("attempt outside the frozen schedule")
                slot = (kind, number, pair)
                if slot in occupied:
                    issues.append(f"duplicate scheduled slot also occupied by {occupied[slot]}")
                if len(slot_directories.get((category, number, pair), [])) > 1:
                    issues.append("multiple retained directories occupy this scheduled slot")
                occupied[slot] = run_dir.name
                intent, record = {}, {}
                status = "interrupted"
                for name, target in (("attempt-intent.json", intent), ("run-record.json", record)):
                    if (run_dir / name).is_file():
                        try:
                            target.update(_json(run_dir / name))
                            if target.get("run_id") != run_dir.name or target.get("repeat", target.get("round")) != number:
                                raise ValueError("attempt record identity/round mismatch")
                            if name == "attempt-intent.json" and (target.get("kind"), target.get("scenario")) != (kind, pair):
                                raise ValueError("attempt intent kind/pair mismatch")
                        except (ValueError, OSError, TypeError) as exc:
                            issues.append(f"{name}: {type(exc).__name__}: {exc}")
                            if name == "run-record.json":
                                status = "failed"
                if record:
                    status = record.get("status", "failed")
                    if status not in ("complete", "failed", "interrupted"):
                        issues.append("unknown terminal status")
                        status = "failed"
                    command = record.get("command", [])
                    try:
                        declared_pair = f"{command[command.index('--orbit-backend') + 1]}-{command[command.index('--magnetic-backend') + 1]}"
                        if declared_pair != pair:
                            raise ValueError("terminal command backend pair mismatch")
                    except (ValueError, IndexError, TypeError, AttributeError) as exc:
                        issues.append(f"terminal command: {exc}")
                reconciliation = run_dir / "reconciliation-record.json"
                if reconciliation.is_file():
                    try:
                        recovered = _json(reconciliation)
                        if (recovered.get("run_id"), recovered.get("round"), recovered.get("scenario"), recovered.get("kind")) != (run_dir.name, number, pair, kind):
                            raise ValueError("reconciliation identity differs from frozen slot")
                        for key, filename in (("original_record_sha256", "run-record.json"), ("intent_sha256", "attempt-intent.json")):
                            if recovered.get(key) and sha256_file(run_dir / filename) != recovered[key]:
                                raise ValueError("reconciled original bytes changed")
                        status = recovered["status"]
                        if status not in ("complete", "failed", "interrupted"):
                            raise ValueError("invalid reconciliation status")
                    except (ValueError, KeyError, OSError, TypeError) as exc:
                        issues.append(f"reconciliation: {type(exc).__name__}: {exc}")
                        status = "failed"
                products = None
                if status == "complete":
                    try:
                        products = validate_saved_products(record, paths, measurements=expected_measurements, tles=experiment["tles"],
                                                           specs=specs, expected_block=block)
                        if not products["passed"]:
                            raise ValueError("retained science/image product audit failed")
                    except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
                        issues.append(f"saved products: {type(exc).__name__}: {exc}")
                        status = "failed"
                worker_seconds = _duration(record.get("external_wall_seconds"))
                worker_scope = record.get("process_execution", {}).get("external_timer_scope")
                if worker_seconds is None and (run_dir / "child-timing.json").is_file():
                    try:
                        timing = _json(run_dir / "child-timing.json")
                        worker_seconds = _duration(timing.get("worker_launch_to_exit_seconds"))
                        worker_scope = timing.get("scope")
                    except (ValueError, OSError) as exc:
                        issues.append(f"child timing: {exc}")
                cycle_seconds = None
                cycle_status = "unavailable_uncommitted"
                if (run_dir / "cycle-timing.json").is_file():
                    try:
                        cycle = _json(run_dir / "cycle-timing.json")
                        if cycle.get("run_id") != run_dir.name or cycle.get("schema_version") != 2:
                            raise ValueError("cycle timing identity/boundary mismatch")
                        cycle_seconds = _duration(cycle.get("full_cycle_seconds"))
                        if cycle_seconds is None or (worker_seconds is not None and cycle_seconds < worker_seconds):
                            raise ValueError("invalid cycle duration")
                        cycle_status = "available"
                    except (ValueError, OSError) as exc:
                        issues.append(f"cycle timing: {exc}")
                order = execution.get(run_dir.name, {})
                controls = controlled_settings(experiment, block) if block and experiment["provenance_available"] else None
                yield {
                    "experiment_id": experiment["identity"], "device_label": experiment["state"].get("device_label"),
                    "session_id": f"{experiment['identity']}:session-{block_info['session_index']}",
                    "session_index": block_info["session_index"], "block_id": block_info["id"], "block_path": block_path,
                    "block_position": block_info["position"], "run_id": run_dir.name, "attempt_number": number,
                    "kind": kind, "pair": pair, "recorded_status": record.get("status"), "status": status,
                    "classification": "excluded_corrupt_or_uncontrolled" if issues or controls is None else "diagnostic_saved_product_valid" if status == "complete" else status,
                    "issues": issues, "checkpoint_indexed": run_dir.name in execution,
                    "directory": str(run_dir), "started_utc": record.get("started_utc", intent.get("started_utc")),
                    "worker_seconds": worker_seconds, "worker_timer_scope": worker_scope,
                    "full_cycle_seconds": cycle_seconds, "cycle_timing_status": cycle_status,
                    "cooldown": order.get("cooldown"), "controls": controls,
                    "cohort_id": _digest({"pair": pair, "controls": controls}) if controls else None,
                    "observations": record.get("observations"), "storage": record.get("storage"),
                    "error_type": record.get("error_type"), "error": record.get("error"),
                    "failure_class": record.get("failure_class"), "hardware_counters": record.get("hardware_counters"),
                    "record_sha256": sha256_file(run_dir / "run-record.json") if (run_dir / "run-record.json").is_file() else None,
                    "stages": products["stage_records"] if products is not None else [], "products": products,
                }
        # A checkpoint can survive deletion/loss of the attempt it references.
        # Such a slot is lost/failed, not an unstarted job eligible for retry.
        present = {path.name for category in ("runs", "warmups") for path in (block_dir / category).glob("*/*") if path.is_dir()}
        for identity, item in sorted(execution.items()):
            if identity in present:
                continue
            controls = controlled_settings(experiment, block) if block and experiment["provenance_available"] else None
            yield {"experiment_id": experiment["identity"], "device_label": experiment["state"].get("device_label"),
                   "session_id": f"{experiment['identity']}:session-{block_info['session_index']}",
                   "session_index": block_info["session_index"], "block_id": block_info["id"], "block_path": block_path,
                   "block_position": block_info["position"], "run_id": identity, "attempt_number": item.get("round"),
                   "kind": item.get("kind", "measured"), "pair": item.get("scenario"), "recorded_status": item.get("status"),
                   "status": "failed", "classification": "excluded_missing_retained_attempt",
                   "issues": ["checkpoint references a missing retained attempt directory"], "checkpoint_indexed": True,
                   "directory": None, "started_utc": item.get("started_utc"), "worker_seconds": None,
                   "worker_timer_scope": None, "full_cycle_seconds": None, "cycle_timing_status": "unavailable_missing_attempt",
                   "cooldown": item.get("cooldown"), "controls": controls,
                   "cohort_id": _digest({"pair": item.get("scenario"), "controls": controls}) if controls else None,
                   "observations": None, "storage": None, "error_type": None, "error": None,
                   "failure_class": "retained_product_integrity", "hardware_counters": None,
                   "record_sha256": None, "stages": [], "products": None}
