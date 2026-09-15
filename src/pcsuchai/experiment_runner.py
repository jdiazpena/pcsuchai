"""Manifest-driven sessions and blocks around the complete production pipeline."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from itertools import product
from pathlib import Path

from .experiment import ExperimentManifest, balanced_order
from .experiment_control import graceful_signals, numerical_controls, process_identity
from .run_lock import serialized_run


def safe_name(value: str) -> str:
    """Make a label safe for directories without accepting traversal or blanks."""

    result = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    if not result:
        raise ValueError("label must contain a letter or number")
    return result


def experiment_blocks(manifest: ExperimentManifest) -> list[dict]:
    """Freeze all independent sessions and declared workload/profile blocks.

    Equal-work pairs are interleaved in a balanced suite. Sustained, persistent
    and counter experiments use one pair per block. Variant/block positions
    rotate across sessions; exact position balance requires a complete cycle.
    No thermal cooldown occurs inside a sustained/persistent measured block.
    """

    data = manifest.data
    work, execution, observation = data["workload"], data["execution"], data["observation"]
    variants = []
    groups = observation["counter_groups"] or [None]
    pair_sets = [[pair] for pair in work["pairs"]] if execution["ordering"] == "scenario_blocks" else [work["pairs"]]
    for size, profile, level, group, pairs in product(work["selection"]["sizes"], work["plot_profiles"], observation["levels"], groups, pair_sets):
        variant = {"size": size, "selection_method": work["selection"]["method"],
                   "plot_profile": profile, "observation_level": level, "counter_group": group, "pairs": pairs}
        variant["id"] = hashlib.sha256(json.dumps(variant, sort_keys=True).encode()).hexdigest()[:16]
        variants.append(variant)
    by_id = {variant["id"]: variant for variant in variants}
    blocks = []
    for session in range(1, data["sessions"] + 1):
        for position, identity in enumerate(balanced_order(list(by_id), session, 1, execution["seed"]), 1):
            blocks.append({**by_id[identity], "session_index": session, "position": position,
                           "path": f"sessions/session-{session:04d}/block-{position:04d}-{identity}", "status": "pending"})
    return blocks


def _counts(state: dict, directory: Path | None = None) -> dict:
    """Account for all fixed slots, including unstarted/failed/interrupted work."""

    data = state["manifest"]
    stop = data["execution"]["stop"]
    scheduled = sum(len(block["pairs"]) for block in state["blocks"]) * stop["value"] if stop["kind"] == "attempts_per_pair" else None
    result = {"scheduled": scheduled, "started": 0, "scientifically_valid": 0, "failed": 0, "interrupted": 0, "automatic_retries": 0}
    for block in state["blocks"]:
        counts = block.get("attempt_counts", {})
        if directory is not None and block["status"] == "running":
            checkpoint = directory / block["path"] / "benchmark-session.checkpoint.json"
            if checkpoint.is_file():
                from .experiment_control import session_attempt_counts
                counts = session_attempt_counts(json.loads(checkpoint.read_text()))
        for key in ("started", "scientifically_valid", "failed", "interrupted"):
            result[key] += counts.get(key, 0)
    result["skipped"] = max(0, scheduled - result["started"]) if scheduled is not None else None
    return result


def _file_hashes(data: dict, root: Path) -> dict:
    """Resolve and hash every declared input/profile before permitting execution."""

    from .benchmark import sha256_file
    paths = {key: root / data["workload"][key] for key in ("measurements", "tle", "eop")}
    paths.update({f"plot:{profile['name']}": root / profile["config"] for profile in data["workload"]["plot_profiles"] if profile["config"]})
    result = {}
    for key, path in paths.items():
        if not path.is_file():
            raise ValueError(f"missing experiment input {key}: {path}")
        result[key] = {"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
    return result


@serialized_run
def run_experiment(manifest: ExperimentManifest, output_dir: str | Path, project_root: str | Path,
                   device_label: str, *, resume: bool = False, prepared: bool = False) -> dict:
    """Run/recover a frozen manifest with one device lock and immutable attempts.

    ``prepared`` is for the detached launcher's newly reserved directory only.
    Resume may start a new worker segment, but never repeats terminal attempts.
    Scientific validation and compilation are outside measured duration clocks.
    Independent sessions/blocks remain explicit in records and comparisons.
    """

    from .campaign_costs import CampaignCosts, cost_clock
    segment_started = cost_clock()

    from .benchmark import runtime_metadata
    from .benchmark_suite import _atomic_write_json, _source_digest, _utc_path_stamp, _utc_text, run_benchmark_suite
    from .retention import snapshot_inputs, snapshot_sources

    destination, root = Path(output_dir).resolve(), Path(project_root).resolve()
    data = manifest.data
    safe_name(device_label)
    hashes = _file_hashes(data, root)
    source, runtime = _source_digest(root), runtime_metadata()
    state_path = destination / "experiment-state.json"
    if resume:
        state = json.loads(state_path.read_text())
        checks = {"manifest": state["manifest_sha256"] == manifest.sha256,
                  "source": state["source"]["sha256"] == source["sha256"],
                  "runtime": state["runtime"] == runtime, "device_label": state["device_label"] == device_label,
                  "inputs": {key: value["sha256"] for key, value in state["inputs"].items()} == {key: value["sha256"] for key, value in hashes.items()}}
        if not all(checks.values()):
            raise ValueError(f"resume contract changed: {[key for key, passed in checks.items() if not passed]}")
        if state["status"] == "complete":
            raise ValueError("completed experiments cannot be resumed")
    else:
        if prepared:
            if state_path.exists() or not destination.is_dir() or ExperimentManifest.load(destination / "manifest.json").sha256 != manifest.sha256:
                raise ValueError("detached preparation does not identify a new matching experiment")
        else:
            destination.mkdir(parents=True, exist_ok=False)
            _atomic_write_json(destination / "manifest.json", data)
        state = {"schema_version": 1, "manifest": data, "manifest_sha256": manifest.sha256,
                 "source": source, "runtime": runtime, "inputs": hashes, "device_label": device_label,
                 "started_utc": _utc_text(), "blocks": experiment_blocks(manifest), "segments": [],
                 "classification": "diagnostic_non_official", "status": "running"}
        state["input_snapshots"] = snapshot_inputs({f"{safe_name(key)}-{hashlib.sha256(key.encode()).hexdigest()[:8]}": Path(value["path"]) for key, value in hashes.items()}, destination / "inputs")
        state["source_snapshot"] = snapshot_sources(root, source, destination / "source-snapshot.tar.gz")
    segment_id = _utc_path_stamp()
    segment_dir = destination / "segments" / segment_id
    segment_dir.mkdir(parents=True, exist_ok=False)
    costs = CampaignCosts(segment_dir, segment_started)
    state["segments"].append({"id": segment_id, "identity": process_identity(), "started_utc": _utc_text(), "resume": resume})
    state.update(status="running", reason=None, phase="setup")
    stop_event = threading.Event()

    def checkpoint() -> None:
        """Commit counts and state without replacing any terminal attempt record."""

        state["attempt_counts"] = _counts(state)
        _atomic_write_json(state_path, state)

    def stopped() -> bool:
        """Observe this segment's file/signal request without deleting older ones."""

        return stop_event.is_set() or (segment_dir / "stop-request.json").exists()

    def unchanged_contract() -> None:
        """Refuse further work or certification if source/input bytes changed."""

        if _source_digest(root)["sha256"] != state["source"]["sha256"]:
            raise ValueError("source changed during experiment; unstarted blocks retained")
        actual = _file_hashes(data, root)
        if {key: item["sha256"] for key, item in actual.items()} != {key: item["sha256"] for key, item in hashes.items()}:
            raise ValueError("input changed during experiment; unstarted blocks retained")

    def full_validation() -> bool:
        """Execute/verify full scientific acceptance, never inside timing blocks."""

        from .full_validation import run_full_validation, verify_validation_certificate
        certificate = state.get("full_validation_certificate")
        plot = root / "configs/plots/archive-full.json"
        if certificate:
            check = costs.call("verify_full_certificate", verify_validation_certificate, destination / certificate, root, hashes["measurements"]["path"], hashes["tle"]["path"], hashes["eop"]["path"], plot, None)
            if not check["passed"]:
                raise ValueError("saved full validation certificate no longer matches the experiment")
            return True
        state["phase"] = "full_scientific_validation"
        checkpoint()
        path = destination / "validation" / _utc_path_stamp()
        result = costs.call("full_scientific_validation", run_full_validation, path, root, hashes["measurements"]["path"], hashes["tle"]["path"], hashes["eop"]["path"], plot)
        state["full_validation_certificate"] = str(Path(result["certificate_path"]).relative_to(destination))
        state["full_validation_status"] = result["status"]
        checkpoint()
        return result["status"] == "pass" and result["official_eligible"]

    checkpoint()
    try:
        with graceful_signals(stop_event), numerical_controls(data["execution"]["threads"], data["execution"]["affinity"]) as controls:
            state["controls"] = controls
            from .preflight import run_preflight
            orbits = tuple(dict.fromkeys(pair.split("-")[0] for pair in data["workload"]["pairs"]))
            magnetic = tuple(dict.fromkeys(pair.split("-")[1] for pair in data["workload"]["pairs"]))
            preflight = costs.call("preflight", run_preflight, root, segment_dir / "preflight", orbits, magnetic,
                                      version_policy=None if data["validation"]["allow_version_drift"] else root / "requirements/rpi-version-policy.txt",
                                      minimum_free_bytes=data["retention"]["minimum_free_bytes"],
                                      selected_backends_only=not data["validation"]["require_full_certificate"])
            _atomic_write_json(segment_dir / "preflight.json", preflight)
            if preflight["status"] != "pass":
                raise ValueError(f"preflight failed: {preflight['failed_checks']}")
            from .provenance import experiment_provenance
            provenance = costs.call("provenance", experiment_provenance, root, data["workload"]["pairs"], destination,
                                               data.get("system_notes"), full_validation=data["validation"]["require_full_certificate"] or
                                               (data["kind"] == "acceptance" and len(data["workload"]["pairs"]) == 4))
            _atomic_write_json(segment_dir / "provenance.json", provenance)
            state["segments"][-1]["provenance_path"] = str((segment_dir / "provenance.json").relative_to(destination))
            checkpoint()
            if provenance["dependency_closure"]["status"] != "pass":
                raise ValueError(f"SUCHAI runtime dependency closure failed: {provenance['dependency_closure']['errors']}")
            if data["kind"] != "acceptance" and data["validation"]["require_full_certificate"] and not stopped():
                if not full_validation():
                    raise ValueError("full scientific acceptance failed")
            for block in state["blocks"]:
                if stopped():
                    state["reason"] = "operator graceful stop"
                    break
                if block["status"] == "complete":
                    continue
                unchanged_contract()
                path = destination / block["path"]
                existing_checkpoint = path / "benchmark-session.checkpoint.json"
                if (path / "benchmark-session.json").is_file():
                    saved = json.loads((path / "benchmark-session.json").read_text())
                    if saved["status"] == "complete":
                        block.update(status="complete", attempt_counts=saved["attempt_counts"], report_path=str((path / "benchmark-session.json").relative_to(destination)))
                        checkpoint()
                        continue
                block.update(status="running", started_utc=block.get("started_utc", _utc_text()))
                state["phase"] = f"session {block['session_index']} block {block['position']}"
                checkpoint()
                stop_rule = data["execution"]["stop"]
                try:
                    result = costs.call("block_execution", run_benchmark_suite,
                        path, hashes["measurements"]["path"], hashes["tle"]["path"], hashes["eop"]["path"],
                        scenario_pairs=tuple(block["pairs"]), plot_config=root / block["plot_profile"]["config"] if block["plot_profile"]["config"] else None,
                        repeats=stop_rule["value"] if stop_rule["kind"] == "attempts_per_pair" else None,
                        duration_seconds=stop_rule["value"] if stop_rule["kind"] == "duration_per_pair_seconds" else None,
                        warmups=data["execution"]["warmups"], seed=data["execution"]["seed"], limit=block["size"],
                        selection_method=block["selection_method"], observation_level=block["observation_level"],
                        stage_interval_seconds=data["observation"]["stage_interval_seconds"],
                        native_memory_interval_seconds=data["observation"]["native_memory_interval_seconds"],
                        telemetry_interval_seconds=data["observation"]["board_interval_seconds"],
                        process_mode=data["execution"]["process_mode"], thread_policy=data["execution"]["threads"],
                        timeout_seconds=data["execution"]["timeout_seconds"], project_root=root, device_label=device_label,
                        session_index=block["session_index"], ordering="balanced",
                        thermal_policy=data["thermal"]["policy"], thermal_between_attempts=data["thermal"]["mode"] == "stable_each_attempt",
                        maximum_temperature_c=data["thermal"]["maximum_temperature_c"],
                        require_temperature_sensor=data["thermal"].get("require_temperature_sensor", False),
                        minimum_free_bytes=data["retention"]["minimum_free_bytes"],
                        continue_on_error=data["execution"]["failure_policy"] == "continue",
                        max_consecutive_failures=data["execution"]["max_consecutive_failures"],
                        counter_group=tuple(block["counter_group"]) if block["counter_group"] else None,
                        minimum_counter_coverage_percent=data["observation"]["minimum_counter_coverage_percent"],
                        stop_requested=stopped, resume=existing_checkpoint.is_file(),
                    )
                    block.update(status=result["status"], attempt_counts=result["attempt_counts"],
                                 report_path=str(Path(result["report_path"]).relative_to(destination)), reason=result.get("stop_reason"))
                except Exception as exc:
                    block.update(status="failed", error_type=type(exc).__name__, reason=str(exc))
                    if existing_checkpoint.is_file():
                        from .experiment_control import session_attempt_counts
                        saved = json.loads(existing_checkpoint.read_text())
                        block["attempt_counts"] = session_attempt_counts(saved) if "execution_order" in saved else saved.get("attempt_counts", {})
                    checkpoint()
                    if data["execution"]["failure_policy"] == "stop":
                        raise
                checkpoint()
                if block["status"] != "complete" and data["execution"]["failure_policy"] == "stop":
                    state["reason"] = block.get("reason") or "block did not complete"
                    break
            if data["kind"] == "acceptance" and (data["validation"]["require_full_certificate"] or set(data["workload"]["pairs"]) == {f"{orbit}-{mag}" for orbit in ("astropy", "skyfield") for mag in ("aacgmv2", "apexpy")}) and all(block["status"] == "complete" for block in state["blocks"]) and not stopped():
                if not full_validation():
                    raise ValueError("full scientific acceptance after smoke check failed")
            unchanged_contract()
            state["status"] = "complete" if all(block["status"] == "complete" for block in state["blocks"]) and not stopped() else "stopped"
            if state.get("full_validation_certificate"):
                # Validate actual saved variants, not just the generic golden
                # pipeline. This follows measurement/worker shutdown and cannot
                # consume their requested duration or contaminate job timings.
                from .saved_attempts import saved_experiment
                from .validation_reference import audit_experiment_workloads
                state["phase"] = "postmeasurement_workload_acceptance"
                checkpoint()
                acceptance_path = destination / "acceptance" / segment_id
                saved_evidence = costs.call("prepare_postmeasurement_saved_evidence", saved_experiment, destination)
                acceptance = costs.call("postmeasurement_workload_acceptance", audit_experiment_workloads, saved_evidence, acceptance_path)
                state["workload_acceptance"] = {"status": acceptance["status"], "attempt_counts": acceptance["attempt_counts"],
                                                "report_path": str((acceptance_path / "workload-acceptance.json").relative_to(destination)),
                                                "wall_seconds": acceptance["wall_seconds"], "process_cpu_seconds": acceptance["process_cpu_seconds"]}
                if acceptance["status"] != "accepted" and state["status"] == "complete":
                    state.update(status="stopped", reason="exact saved-workload full-reference scientific acceptance failed/incomplete")
                state["scientific_classification"] = "full_reference_workloads_accepted" if acceptance["status"] == "accepted" else "scientifically_incomplete_or_failed"
            state["reason"] = "operator graceful stop" if stopped() else state.get("reason")
            if state["status"] == "stopped" and state["reason"] is None:
                state["reason"] = "one or more blocks incomplete; inspect retained block reasons"
    except BaseException as exc:
        state.update(status="stopped", reason=f"{type(exc).__name__}: {exc}", error_type=type(exc).__name__)
        checkpoint()
        raise
    finally:
        state["phase"] = "finished"
        state["finished_utc"] = _utc_text()
        state["segments"][-1].update(finished_utc=state["finished_utc"], status=state["status"])
        try:
            costs.call("final_state_commit", checkpoint)
            from .storage import filesystem_capacity
            costs.call("final_storage_observation", _atomic_write_json,
                       segment_dir / "storage-final.json", filesystem_capacity(destination))
        finally:
            costs.finish(state["status"])
    return {"status": state["status"], "directory": str(destination), "attempt_counts": state["attempt_counts"], "reason": state.get("reason")}
