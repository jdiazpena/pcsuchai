"""Reconstruct retention costs and conditional forecasts from all saved attempts."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict

from .storage import _nonnegative, forecast_storage, inventory_storage
from .saved_attempts import _json


def report_storage(experiments: list[dict], attempts: list[dict], destination, *,
                   planned_attempts: int | None = None, reserve_bytes: int | None = None) -> dict:
    """Save every attempt's cost, without hiding failures or fabricating old data.

    Forecasts stay within exact workload/system cohorts. Each supplied planned
    count applies to that cohort and includes warmups and failures. Capacity is
    the latest saved target observation, never today's analysis-machine space.
    Current-tree allocation is separately labelled and can differ after import.
    """

    groups = defaultdict(list)
    final_capacities = {}
    final_capacity_issues = []
    for experiment in experiments:
        saved = []
        for path in sorted((experiment["root"] / "segments").glob("*/storage-final.json")):
            try:
                if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(experiment["root"].resolve()):
                    raise ValueError("unsafe linked final-capacity path")
                capacity = _json(path)
                if capacity.get("scope") == "retention_filesystem" and isinstance(capacity.get("captured_utc"), str):
                    saved.append(capacity)
                else:
                    raise ValueError("invalid final capacity scope/timestamp")
            except (ValueError, OSError, UnicodeError) as exc:
                final_capacity_issues.append({"experiment_id": experiment["identity"], "path": str(path), "error": str(exc)})
        final_capacities[experiment["identity"]] = saved
    with gzip.open(destination / "storage-costs.jsonl.gz", "xt", encoding="utf-8") as journal:
        for attempt in attempts:
            storage = attempt.get("storage")
            journal.write(json.dumps({"experiment_id": attempt["experiment_id"], "run_id": attempt["run_id"],
                                      "device_label": attempt["device_label"], "cohort_id": attempt["cohort_id"],
                                      "kind": attempt["kind"], "status": attempt["status"],
                                      "recorded_status": attempt.get("recorded_status"), "saved_storage_record": storage},
                                     separators=(",", ":"), allow_nan=False) + "\n")
            groups[(attempt["cohort_id"], attempt["device_label"])].append(attempt)
    reports = []
    for (cohort, device), records in sorted(groups.items(), key=lambda item: str(item[0])):
        storages = [item["storage"] if isinstance(item.get("storage"), dict) else {} for item in records]
        metrics = {}
        for metric in ("retention_wall_seconds", "compression_wall_seconds", "sharing_wall_seconds",
                       "logical_product_bytes", "new_content_bytes", "new_retained_file_allocated_bytes",
                       "new_retained_file_inodes", "shared_files", "fallback_files",
                       "parent_compression_original_bytes", "parent_compression_saved_bytes", "parent_compression_file_count"):
            values = [saved.get(metric) for saved in storages]
            known = [value for value in values if _nonnegative(value)]
            metrics[metric] = {"available_attempts": len(known), "unavailable_attempts": len(values) - len(known),
                               "sum_of_available_values": sum(known) if known else None,
                               "minimum": min(known, default=None), "maximum": max(known, default=None),
                               "mean_of_available_values": sum(known) / len(known) if known else None}
        capacities = [saved.get("capacity_after_retention") for saved in storages]
        for identity in {item["experiment_id"] for item in records}:
            capacities.extend(final_capacities.get(identity, []))
        capacities = [capacity for capacity in capacities if isinstance(capacity, dict) and isinstance(capacity.get("captured_utc"), str)]
        capacity = max(capacities, key=lambda item: item["captured_utc"], default={"status": "unavailable", "reason": "no saved retention capacity"})
        growth = [saved.get("observed_filesystem_growth_bytes") for saved in storages]
        inode_growth = [saved.get("observed_filesystem_growth_inodes") for saved in storages]
        if cohort is None:
            forecast = {"status": "unavailable", "reason": "unclassified workload controls cannot be extrapolated", "guaranteed_to_fit": False}
        else:
            forecast = forecast_storage(growth, inode_growth, capacity, planned_attempts=planned_attempts, reserve_bytes=reserve_bytes)
        reports.append({"cohort_id": cohort, "device_label": device, "pair": records[0]["pair"],
                        "all_started_attempts": len(records), "warmup_attempts": sum(item["kind"] == "warmup" for item in records),
                        "noncomplete_attempts": sum(item["status"] != "complete" for item in records),
                        "retention_metrics": metrics, "forecast": forecast,
                        "allocation_limit": "attributed file blocks are a lower bound, not total growth; forecast uses whole-filesystem observations including unrelated activity",
                        "cost_limit": "parent compression/sharing only; worker-internal compression already lies inside worker/stage timers"})
    trees = []
    for experiment in experiments:
        try:
            tree = inventory_storage(experiment["root"], scope="current_analysis_filesystem_tree")
        except OSError as exc:
            tree = {"allocation_status": "unavailable", "reason": str(exc)}
        trees.append({"experiment_id": experiment["identity"], "directory": str(experiment["root"]), **tree})
    return {"groups": reports, "current_analysis_tree_inventories": trees, "raw_journal": "storage-costs.jsonl.gz",
            "final_capacity_issues": final_capacity_issues,
            "raw_attempts_pruned": False, "capacity_limit": "saved capacity can be stale; recheck on the target before launch; no guarantee against a job's temporary peak or concurrent activity",
            "forecast_scope": "largest observed whole-filesystem byte/inode growth per started job, same workload; supplied reserve covers unmeasured staging/commit/setup/finalization"}
