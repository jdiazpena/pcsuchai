"""Reports reconstructed from immutable raw attempts and observation journals.

No final summary supplies the timing samples. Failures/partial attempts remain
in counts and journals, but not successful-job latency estimates. The report
does not upgrade a product-integrity check into absolute scientific acceptance.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from .run_lock import serialized_run
from .saved_attempts import _digest, _duration, iter_saved_attempts, saved_experiment
from .session_statistics import session_ratio, session_statistics
from .reading_statistics import ReadingTrend
from .operation_costs import measured_operation


def _observations(experiment: dict, handle, trends: dict, issues: list):
    """Stream complete block journals once, with fallback for partial attempts.

    The global journal contains idle/warm-up/measured contexts. Per-attempt copies
    are not read again when it exists. Every structured value/source/status/time
    remains in the compressed report journal; only scalar values have slopes.
    """

    root = experiment["root"]
    samples = 0
    for block in sorted(root.glob("sessions/session-*/block-*")):
        files = sorted(block.glob("system-telemetry.*.csv*"))
        # Prefer closed compressed copies if both original and gzip survived.
        files = [path for path in files if path.suffix == ".gz" or not path.with_name(path.name + ".gz").exists()]
        if not files:
            files = [path for category in ("runs", "warmups") for path in sorted((block / category).glob("*/*/system-telemetry.csv*"))]
            files = [path for path in files if path.suffix == ".gz" or not path.with_name(path.name + ".gz").exists()]
        for path in files:
            opener = gzip.open if path.suffix == ".gz" else open
            try:
                with opener(path, "rt", encoding="utf-8", newline="") as source:
                    for number, row in enumerate(csv.DictReader(source), 2):
                        try:
                            observations = json.loads(row.get("observations_json") or "{}")
                            if not isinstance(observations, dict):
                                raise ValueError("observation cell is not an object")
                            record = {"experiment_id": experiment["identity"], "device_label": experiment["state"].get("device_label"),
                                      "block_path": block.relative_to(root).as_posix(), "journal": path.relative_to(root).as_posix(),
                                      "csv_line": number, "raw_csv_fields": row, "observations": observations}
                            handle.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
                            samples += 1
                            # schema_version is envelope metadata, not a role.
                            # Keep the entire envelope in the raw journal while
                            # only interpreting the three declared role maps.
                            for role in ("board", "worker", "supervisor"):
                                readings = observations.get(role, {})
                                if not isinstance(readings, dict):
                                    issues.append({"experiment_id": experiment["identity"], "journal": str(path), "csv_line": number,
                                                   "classification": "malformed_observation_role_retained_in_original", "role": role})
                                    continue
                                for name, reading in readings.items():
                                    if not isinstance(reading, dict) or "status" not in reading:
                                        continue
                                    key = (experiment["identity"], record["block_path"], row.get("segment_id"), role,
                                           name, reading.get("source"), reading.get("scope"), reading.get("unit"))
                                    trends.setdefault(key, ReadingTrend()).add(reading)
                        except (ValueError, TypeError) as exc:
                            issues.append({"experiment_id": experiment["identity"], "journal": str(path), "csv_line": number,
                                           "classification": "malformed_observation_retained_in_original", "error": str(exc)})
            except (ValueError, OSError, EOFError, csv.Error) as exc:
                issues.append({"experiment_id": experiment["identity"], "journal": str(path),
                               "classification": "partial_or_corrupt_observation_journal", "error": str(exc)})
    return samples


def _latencies(attempts: list, metric: str) -> dict:
    """Collect scientifically checked complete measured attempts by session."""

    result = defaultdict(list)
    for item in attempts:
        value = item.get(metric)
        if item["kind"] == "measured" and item["status"] == "complete" and not item["issues"] and value is not None:
            result[item["session_id"]].append(value)
    return dict(result)


def _counts(attempts: list) -> dict:
    """Retain all failed/interrupted/excluded slots in the started denominator."""

    measured = [item for item in attempts if item["kind"] == "measured"]
    failures = sum(item["status"] == "failed" for item in measured)
    return {"started": len(measured), "product_valid": sum(item["status"] == "complete" and not item["issues"] for item in measured),
            "full_reference_accepted": sum(item.get("workload_acceptance", {}).get("passed") is True and not item["issues"] for item in measured),
            "failed": failures, "interrupted": sum(item["status"] == "interrupted" for item in measured),
            "excluded": sum(bool(item["issues"]) or item["cohort_id"] is None for item in measured),
            "failed_fraction_of_started": failures / len(measured) if measured else None,
            "warmup_started": sum(item["kind"] == "warmup" for item in attempts), "automatic_retries": 0}


def _science_identity(attempt: dict) -> str:
    """Freeze scientific work independently of observation/process lifetime.

    Recomputing identical work must retain the same scientific arrays even if
    timing instrumentation, process lifetime or thread limits are intentionally
    varied. Input/source/package/row/filter/backend differences are never merged.
    """

    controls = attempt["controls"]
    return _digest({"pair": attempt["pair"], **{key: controls[key] for key in
                    ("source_sha256", "inputs", "python_version", "packages", "selection", "plot_profile")}})


def _overhead(groups: dict, *, seed: int, resamples: int) -> list[dict]:
    """Compare declared levels against minimal in matching independent sessions.

    Only the ``overhead`` protocol is eligible; normal measurements from an
    arbitrary thermal block are not a matched calibration. All controls except
    observation level must match, and partial session pairing is unavailable.
    The measured difference is reported, never subtracted from primary timings.
    """

    cohorts = defaultdict(dict)
    for (_identity, device), records in groups.items():
        controls = records[0]["controls"]
        if controls["kind"] != "overhead":
            continue
        comparison = json.loads(json.dumps(controls))
        level = comparison["observation"]["levels"][0]
        comparison["observation"].pop("levels")
        identity = _digest({"device": device, "pair": records[0]["pair"], "controls": comparison})
        cohorts[identity].setdefault(level, []).extend(records)
    reports = []
    for identity, levels in cohorts.items():
        if "minimal" not in levels:
            reports.append({"matched_control_id": identity, "status": "unavailable", "reason": "no minimally instrumented matched baseline"})
            continue
        for level, records in sorted(levels.items()):
            if level == "minimal":
                continue
            for metric in ("worker_seconds", "full_cycle_seconds"):
                ratio = session_ratio(_latencies(levels["minimal"], metric), _latencies(records, metric),
                                      paired=True, seed=seed, resamples=resamples)
                interval = ratio.get("uncertainty", {}).get("interval")
                reports.append({"matched_control_id": identity, "level": level, "baseline": "minimal",
                                "device_label": records[0]["device_label"], "pair": records[0]["pair"], "metric": metric,
                                "overhead_percent": (1 / ratio["ratio"] - 1) * 100 if ratio["ratio"] else None,
                                "overhead_percent_interval": [(1 / value - 1) * 100 for value in reversed(interval)] if interval else None,
                                "latency_ratio": ratio, "assumed_overhead_subtracted": False})
    return reports


@serialized_run
@measured_operation("report", "output_dir", input_argument="directories")
def report_experiments(directories: list[str | Path], output_dir: str | Path, *,
                       seed: int = 1729, resamples: int = 2000, thermal_policy=None,
                       storage_planned_attempts: int | None = None, storage_reserve_bytes: int | None = None) -> dict:
    """Report saved experiments, supporting repeated sessions on the same board.

    A controlled cohort differs only in its declared board-plus-software system.
    Unmatched settings produce separate cohorts, never silent exclusion. ALL
    attempt rows are retained in attempts.jsonl.gz. Same-cohort same-backend
    raw arrays/filter decisions are checked before timing comparisons. Partial
    reports and numerical disagreements are explicit, not a passing certificate.
    """

    from .portable import METADATA, verify_import
    from .scientific_comparison import compare_scientific_products
    from .storage import forecast_storage

    # Validate operator counts/headroom before creating output or doing science.
    forecast_storage([], [], {}, planned_attempts=storage_planned_attempts, reserve_bytes=storage_reserve_bytes)

    if not directories:
        raise ValueError("at least one saved experiment is required")
    experiments = [saved_experiment(path) for path in directories]
    if any(experiment["live"] for experiment in experiments):
        raise ValueError("stop verified live experiments before reporting on this device")
    identities = [experiment["identity"] for experiment in experiments]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate experiment or imported copy would double-count sessions")
    destination = Path(output_dir).resolve()
    if any(destination.is_relative_to(experiment["root"]) for experiment in experiments):
        raise ValueError("report destination must be outside every immutable experiment")
    for experiment in experiments:
        if (experiment["root"] / METADATA).is_file():
            verify_import(experiment["root"])
    from .validation_reference import load_full_reference, accept_workload_variant
    full_references = {experiment["identity"]: load_full_reference(experiment) for experiment in experiments}
    # Validate resampling options before creating any report files.
    session_statistics({}, seed=seed, resamples=resamples)
    destination.mkdir(parents=True, exist_ok=False)
    attempts, groups, numerical, reference = [], defaultdict(list), [], {}
    issues = []
    with gzip.open(destination / "attempts.jsonl.gz", "xt", encoding="utf-8") as journal, \
            gzip.open(destination / "stages.jsonl.gz", "xt", encoding="utf-8") as stages, \
            gzip.open(destination / "numerical-comparisons.jsonl.gz", "xt", encoding="utf-8") as comparisons:
        for experiment in experiments:
            full_reference = full_references[experiment["identity"]]
            blocks = {block["path"]: block for block in experiment["blocks"]}
            for attempt in iter_saved_attempts(experiment):
                if attempt["controls"] is not None:
                    # Availability is a shared reference/work control. Candidate
                    # success is an outcome, not a different cohort: splitting
                    # on it removes failures from that cohort's denominator.
                    attempt["controls"]["acceptance_evidence_class"] = full_reference["status"]
                    attempt["cohort_id"] = _digest({"pair": attempt["pair"], "controls": attempt["controls"]})
                attempt["workload_acceptance"] = {"status": "not_checked", "passed": False, "reason": "attempt incomplete/excluded"}
                if attempt["status"] == "complete" and attempt["products"] and not attempt["issues"] and attempt["cohort_id"]:
                    acceptance = accept_workload_variant(experiment, full_reference, blocks[attempt["block_path"]], attempt["pair"], attempt["products"])
                    attempt["workload_acceptance"] = acceptance
                    if acceptance["passed"]:
                        attempt["classification"] = "full_reference_workload_accepted"
                    elif acceptance["status"] == "failed":
                        attempt["issues"].append("full-reference exact-workload acceptance failed")
                        attempt["classification"] = "excluded_full_reference_acceptance_failed"
                        if full_reference["passed"]:
                            attempt["status"] = "failed"
                    elif experiment["manifest"]["validation"]["require_full_certificate"]:
                        attempt["issues"].append("required archived full-reference evidence unavailable")
                        attempt["classification"] = "excluded_required_full_reference_unavailable"
                if attempt["status"] == "complete" and attempt["products"] and not attempt["issues"] and attempt["cohort_id"]:
                    identity = _science_identity(attempt)
                    products = attempt["products"]
                    if identity in reference:
                        original = reference[identity]
                        try:
                            check = compare_scientific_products(original["products"]["raw_products"], products["raw_products"],
                                                                reference_selections=tuple(original["products"]["selection_files"]),
                                                                candidate_selections=tuple(products["selection_files"]))
                        except (ValueError, OSError, KeyError, TypeError) as exc:
                            check = {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
                        summary = {"reference_run_id": original["run_id"], "candidate_run_id": attempt["run_id"],
                                   "reference_device": original["device_label"], "candidate_device": attempt["device_label"],
                                   "scientific_work_id": identity, "reference_cohort_id": original["cohort_id"], "candidate_cohort_id": attempt["cohort_id"],
                                   "passed": check["passed"], "journal_line": len(numerical) + 1,
                                   "journal": "numerical-comparisons.jsonl.gz"}
                        comparisons.write(json.dumps({**summary, "full_comparison": check}, separators=(",", ":"), allow_nan=False) + "\n")
                        numerical.append(summary)
                        if not check["passed"]:
                            attempt["status"] = "failed"
                            attempt["classification"] = "excluded_scientific_disagreement"
                            attempt["issues"].append("same-work same-backend raw science/filter disagreement")
                    else:
                        reference[identity] = attempt
                journal.write(json.dumps(attempt, separators=(",", ":"), allow_nan=False) + "\n")
                for record in attempt["stages"]:
                    stages.write(json.dumps({"run_id": attempt["run_id"], "experiment_id": attempt["experiment_id"],
                                             "device_label": attempt["device_label"], "kind": attempt["kind"], "status": attempt["status"],
                                             "stage_record": record}, separators=(",", ":"), allow_nan=False) + "\n")
                # Detailed audits/stages stay in disk journals, not a growing
                # in-memory copy. References retain only paths for the next check.
                compact = {key: value for key, value in attempt.items() if key not in ("products", "stages", "workload_acceptance")}
                compact["workload_acceptance"] = {key: value for key, value in attempt["workload_acceptance"].items() if key != "comparison"}
                compact["products"] = {key: attempt["products"][key] for key in ("raw_products", "selection_files")} if attempt["products"] else None
                attempts.append(compact)
                if attempt["controls"] is not None and reference.get(_science_identity(attempt)) is attempt:
                    reference[_science_identity(attempt)] = compact
                if attempt["cohort_id"]:
                    groups[(attempt["cohort_id"], attempt["device_label"])].append(compact)
    trends, observation_count = {}, 0
    with gzip.open(destination / "observations.jsonl.gz", "xt", encoding="utf-8") as observations:
        for experiment in experiments:
            observation_count += _observations(experiment, observations, trends, issues)
    from .thermal_analysis import report_thermal_readings
    thermal = report_thermal_readings(destination / "observations.jsonl.gz", experiments, destination, policy=thermal_policy)
    issues.extend(thermal["issues"])
    from .report_plotting import render_report_plots
    plots = render_report_plots(destination / "observations.jsonl.gz", attempts, destination)
    from .thermal_plotting import render_thermal_plots
    thermal["plots"] = render_thermal_plots(destination / "observations.jsonl.gz", thermal, destination)
    from .storage_report import report_storage
    storage = report_storage(experiments, attempts, destination, planned_attempts=storage_planned_attempts,
                             reserve_bytes=storage_reserve_bytes)
    from .campaign_cost_report import report_campaign_costs
    campaign_costs = report_campaign_costs(experiments, attempts, destination)
    issues.extend(campaign_costs["issues"])
    from .recovery_cost_report import report_recovery_costs
    recovery_costs = report_recovery_costs(experiments, destination)
    issues.extend(recovery_costs["issues"])
    from .thermal_performance import report_thermal_performance
    thermal_performance = report_thermal_performance(destination / "observations.jsonl.gz", attempts, destination,
                                                       seed=seed, resamples=resamples)
    from .thermal_performance_plotting import render_thermal_performance_plots
    thermal_performance["plots"] = render_thermal_performance_plots(destination / "thermal-performance.jsonl.gz", destination)
    from .resource_report import report_resources
    resources = report_resources(destination / "stages.jsonl.gz", attempts, destination)
    issues.extend(resources["issues"])
    from .scaling_report import report_scaling
    scaling = report_scaling(destination / "attempts.jsonl.gz", destination, seed=seed, resamples=resamples)
    from .scaling_plotting import render_scaling_plots
    scaling["plots"] = render_scaling_plots(scaling, destination)
    cohort_reports = []
    for (identity, device), records in sorted(groups.items(), key=lambda item: str(item[0])):
        worker = _latencies(records, "worker_seconds")
        cycle = _latencies(records, "full_cycle_seconds")
        valid = [item for item in records if item["kind"] == "measured" and item["status"] == "complete" and not item["issues"]]
        busy = sum(item["worker_seconds"] for item in valid if item["worker_seconds"] is not None)
        committed = sum(item["full_cycle_seconds"] for item in valid if item["full_cycle_seconds"] is not None)
        cohort_reports.append({"cohort_id": identity, "device_label": device, "pair": records[0]["pair"],
                               "controlled_settings": records[0]["controls"], "counts": _counts(records),
                               "worker_latency": session_statistics(worker, seed=seed, resamples=resamples),
                               "full_cycle_latency": session_statistics(cycle, seed=seed, resamples=resamples),
                               "valid_jobs_per_worker_busy_second": sum(len(values) for values in worker.values()) / busy if busy else None,
                               "valid_jobs_per_committed_cycle_second": sum(len(values) for values in cycle.values()) / committed if committed else None,
                               "throughput_limit": "successful busy/cycle time only; not campaign throughput including failures/recovery/setup",
                               "cycle_unavailable_attempts": sum(item["full_cycle_seconds"] is None for item in valid)})
    speedups = []
    by_cohort = defaultdict(dict)
    for (identity, device), records in groups.items():
        by_cohort[identity][device] = records
    for identity, devices in by_cohort.items():
        for first, second in combinations(sorted(devices, key=str), 2):
            for metric in ("worker_seconds", "full_cycle_seconds"):
                speedups.append({"cohort_id": identity, "reference_device": first, "candidate_device": second,
                                 "metric": metric, **session_ratio(_latencies(devices[first], metric), _latencies(devices[second], metric),
                                                                   seed=seed, resamples=resamples)})
    overhead = _overhead(groups, seed=seed, resamples=resamples)
    # Stage values come from verified saved benchmark products, not aggregate
    # session summaries. Original detailed stage fields remain in the journal.
    stage_values = defaultdict(lambda: defaultdict(list))
    attempt_by_id = {(item["experiment_id"], item["run_id"]): item for item in attempts}
    with gzip.open(destination / "stages.jsonl.gz", "rt", encoding="utf-8") as stages:
        for line in stages:
            row = json.loads(line)
            attempt = attempt_by_id[(row["experiment_id"], row["run_id"])]
            if attempt["kind"] != "measured" or attempt["status"] != "complete" or attempt["issues"] or not attempt["cohort_id"]:
                continue
            record = row["stage_record"]
            for metric in ("wall_seconds", "process_cpu_seconds", "process_user_seconds", "process_system_seconds"):
                value = _duration(record.get(metric))
                if value is not None:
                    key = (attempt["cohort_id"], attempt["device_label"], attempt["pair"], record["stage"], metric)
                    stage_values[key][attempt["session_id"]].append(value)
    stage_reports = [{"cohort_id": key[0], "device_label": key[1], "pair": key[2], "stage": key[3], "metric": key[4],
                      "statistics": session_statistics(values, seed=seed, resamples=resamples),
                      "limit": "positive measured stage durations; genuine zero CPU durations remain in raw journal but not positive-latency estimates"}
                     for key, values in sorted(stage_values.items(), key=lambda item: str(item[0]))]
    experiment_reports = []
    for experiment in experiments:
        data = experiment["manifest"]
        records = [item for item in attempts if item["experiment_id"] == experiment["identity"]]
        stop = data["execution"]["stop"]
        scheduled = sum(len(block["pairs"]) for block in experiment["blocks"]) * stop["value"] if stop["kind"] == "attempts_per_pair" else None
        counts = _counts(records)
        counts.update(scheduled=scheduled, skipped=max(0, scheduled - counts["started"]) if scheduled is not None else None)
        experiment_reports.append({"experiment_id": experiment["identity"], "directory": str(experiment["root"]),
                                   "device_label": experiment["state"].get("device_label"), "recorded_status": experiment["state"].get("status"),
                                   "runtime": experiment["state"].get("runtime"), "counts": counts,
                                   "issues": experiment["issues"], "block_schedule": experiment["blocks"],
                                   "full_reference": full_references[experiment["identity"]]})
    result = {
        "report_schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "diagnostic_saved_record_analysis_not_complete_scientific_or_hardware_acceptance",
        "comparison_contract": {"intended_variable": "board_plus_software_system", "controlled_settings": "exact per-cohort signature",
                                "system_differences": "OS/kernel/ABI/architecture recorded; not isolated silicon speed",
                                "python_library_drift": "separate cohort", "scientific_limit": "relative same-backend fidelity; own-model invariants are not independent absolute reference truth"},
        "experiments": experiment_reports, "cohorts": cohort_reports, "speedups": speedups,
        "stage_statistics": stage_reports, "instrumentation_overhead": overhead,
        "thermal_analysis": thermal,
        "storage_analysis": storage,
        "campaign_costs": campaign_costs,
        "recovery_costs": recovery_costs,
        "thermal_performance": thermal_performance,
        "resource_analysis": resources,
        "scaling_analysis": scaling,
        "all_attempt_counts": _counts(attempts), "numerical_comparisons": numerical,
        "observation_rows": observation_count, "observation_issues": issues,
        "reading_trends": [{"experiment_id": key[0], "block_path": key[1], "segment_id": key[2], "role": key[3],
                            "metric": key[4], "source": key[5], "scope": key[6], "unit": key[7], **trend.report()}
                           for key, trend in trends.items()],
        "raw_report_journals": ["attempts.jsonl.gz", "stages.jsonl.gz", "observations.jsonl.gz", "numerical-comparisons.jsonl.gz",
                                "thermal-windows.jsonl.gz", "throttle-transitions.jsonl.gz", "storage-costs.jsonl.gz", "campaign-costs.jsonl.gz", "recovery-costs.jsonl.gz", "thermal-performance.jsonl.gz", "hardware-counters.jsonl.gz", "scaling.jsonl.gz"],
        "plots": plots,
        "status": "partial_or_excluded" if any(item["issues"] or item["status"] != "complete" for item in attempts)
                  or any(experiment["issues"] or experiment["state"].get("status") != "complete" for experiment in experiments)
                  or issues else "diagnostic_report_created",
    }
    report_path = destination / "experiment-report.json"
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return {"report_path": str(report_path), "classification": result["classification"], "status": result["status"],
            "attempt_counts": result["all_attempt_counts"], "cohort_count": len(cohort_reports), "observation_rows": observation_count}
