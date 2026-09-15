"""Complete-work scaling across declared input sizes and saved plot contracts."""

from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict

from .saved_attempts import _digest
from .session_statistics import session_ratio, session_statistics


def _number(value):
    """Accept finite nonnegative metrics, including genuine zero."""

    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _scaling_controls(attempt):
    """Vary ONLY selection size and plot contract within the scaling protocol.

    Backend/device remain separate; all threading/process/thermal/observation/
    stop/source/library/selection-method controls remain frozen. Plot input
    hashes belong to the declared plot variable, not the shared historical data.
    Each individual workload still retains its full exact primary cohort.
    """

    controls = attempt.get("controls")
    if not isinstance(controls, dict) or controls.get("kind") != "scaling":
        return None
    common = json.loads(json.dumps(controls))
    common["selection"].pop("size")
    common.pop("plot_profile")
    common["inputs"] = {key: value for key, value in common["inputs"].items() if not key.startswith("plot:")}
    return {"pair": attempt["pair"], "device_label": attempt["device_label"], "controls": common}


def _stage_metrics(stages):
    """Full-chain CPU/I/O sums and sampled RSS peak, without filling gaps."""

    result = {}
    for metric in ("process_cpu_seconds", "read_bytes", "write_bytes", "read_chars", "write_chars"):
        values = [row.get(metric) for row in stages]
        result[metric] = sum(values) if values and all(_number(value) for value in values) else None
        if not _number(result[metric]):
            result[metric] = None
    rss = [row.get("peak_rss_bytes") for row in stages]
    result["sampled_peak_rss_bytes"] = max(rss) if rss and all(_number(value) for value in rss) else None
    return result


def _descriptive(values):
    """Summarize zero-compatible bytes/resources, retaining unavailable count."""

    available = [value for value in values if _number(value)]
    return {"available_attempts": len(available), "unavailable_attempts": len(values) - len(available),
            "minimum": min(available, default=None), "maximum": max(available, default=None),
            "mean": sum(available) / len(available) if available else None,
            "limit": "descriptive observed values; no memory-limit extrapolation or independent-job confidence interval"}


def report_scaling(attempt_journal, destination, *, seed=1729, resamples=2000):
    """Reconstruct declared scaling jobs, failures and profile information intact.

    This is an additional intended-variable contract, not a merger of primary
    equal-work cohorts. It does not recompute models, discard filters, infer a
    link rate, or claim that a bigger output necessarily contains more useful
    science. Uncontrolled/malformed jobs stay in the raw journal, not estimates.
    """

    groups = defaultdict(lambda: defaultdict(list))
    excluded = 0
    with gzip.open(attempt_journal, "rt", encoding="utf-8") as source, gzip.open(destination / "scaling.jsonl.gz", "xt", encoding="utf-8") as journal:
        for line in source:
            attempt = json.loads(line)
            common = _scaling_controls(attempt)
            if common is None:
                continue
            controls = attempt["controls"]
            products = attempt.get("products") or {}
            details = products.get("workload_details") or {}
            rows = details.get("observed_rows", products.get("raw_audit", {}).get("rows"))
            if type(rows) is not int or rows <= 0:
                rows = None
            plots = details.get("plot_products") or []
            sizes = [plot.get("size_bytes") for plot in plots]
            png_bytes = sum(sizes) if sizes and all(type(size) is int and size >= 0 for size in sizes) else None
            metrics = {"worker_seconds": attempt["worker_seconds"], "full_cycle_seconds": attempt["full_cycle_seconds"],
                       **_stage_metrics(attempt.get("stages") or []), "png_bytes": png_bytes,
                       "plot_count": len(plots) if details else None}
            storage = attempt.get("storage") or {}
            for metric in ("logical_product_bytes", "new_content_bytes", "compression_wall_seconds", "retention_wall_seconds"):
                metrics[metric] = storage.get(metric) if _number(storage.get(metric)) else None
            for metric in ("worker_seconds", "full_cycle_seconds", "process_cpu_seconds", "png_bytes"):
                metrics[f"{metric}_per_input_row"] = metrics[metric] / rows if rows and _number(metrics[metric]) else None
            usable = bool(attempt["kind"] == "measured" and attempt["status"] == "complete" and not attempt["issues"] and attempt["cohort_id"] and rows)
            excluded += attempt["kind"] == "measured" and not usable
            variant = {"requested_size": controls["selection"]["size"], "plot_profile": controls["plot_profile"]}
            # Profile rendering/filter changes are part of the variable even
            # when old configurations reused a misleading human name.
            plot_contract = [{key: value for key, value in plot.items() if key in ("name", "format", "width_px", "height_px", "variable", "coordinate_view", "plot_type", "scale", "spec", "geographic_context", "rendering", "threshold")}
                             for plot in plots]
            point = {"experiment_id": attempt["experiment_id"], "session_id": attempt["session_id"], "run_id": attempt["run_id"],
                     "block_path": attempt["block_path"], "device_label": attempt["device_label"], "pair": attempt["pair"],
                     "cohort_id": attempt["cohort_id"], "scaling_control_id": _digest(common), "variant": variant,
                     "kind": attempt["kind"], "status": attempt["status"], "issues": attempt["issues"],
                     "usable_measured": usable, "actual_rows": rows, "selection": details.get("selection"),
                     "plot_products": plots, "plot_contract_id": _digest(plot_contract) if plots else None, "metrics": metrics}
            journal.write(json.dumps(point, separators=(",", ":"), allow_nan=False) + "\n")
            # Success-dependent products cannot define the cohort: failed jobs
            # with no output belong to the same frozen variant's denominator.
            groups[_digest(common)][_digest(variant)].append(point)
    reports = []
    for identity, variants in groups.items():
        summaries, latencies = [], {}
        for variant_id, points in variants.items():
            usable = [point for point in points if point["usable_measured"]]
            measured = [point for point in points if point["kind"] == "measured"]
            latency = {}
            for metric in ("worker_seconds", "full_cycle_seconds", "worker_seconds_per_input_row", "full_cycle_seconds_per_input_row"):
                sessions = defaultdict(list)
                for point in usable:
                    value = point["metrics"][metric]
                    if _number(value) and value > 0:
                        sessions[point["session_id"]].append(value)
                latency[metric] = session_statistics(dict(sessions), seed=seed, resamples=resamples)
                latency[metric]["unit"] = "seconds_per_input_row" if metric.endswith("per_input_row") else "seconds"
                if metric in ("worker_seconds", "full_cycle_seconds"):
                    latencies[(variant_id, metric)] = dict(sessions)
            summaries.append({"variant_id": variant_id, "variant": points[0]["variant"],
                              "actual_row_counts": sorted({point["actual_rows"] for point in usable}),
                              "counts": {"measured_started": len(measured), "usable_measured": len(usable),
                                         "failed_or_interrupted": sum(p["status"] in ("failed", "interrupted") for p in measured),
                                         "excluded_measured": sum(not p["usable_measured"] for p in measured),
                                         "warmup_started": sum(p["kind"] == "warmup" for p in points)},
                              "latency": latency,
                              "resources": {metric: _descriptive([p["metrics"][metric] for p in usable]) for metric in
                                            ("process_cpu_seconds", "process_cpu_seconds_per_input_row", "sampled_peak_rss_bytes", "read_bytes", "write_bytes", "read_chars", "write_chars", "png_bytes", "png_bytes_per_input_row", "plot_count", "logical_product_bytes", "new_content_bytes", "compression_wall_seconds", "retention_wall_seconds")},
                              "plot_contract_ids": sorted({p["plot_contract_id"] for p in usable if p["plot_contract_id"]}),
                              "plot_contract_example": next((p["plot_products"] for p in usable if p["plot_products"]), []),
                              "plot_contract_example_limit": "representative metadata only; every job's exact selected counts/empty filters/bytes remain in scaling.jsonl.gz"})
        ratios = []
        # Compare plots only at the same actual input size; compare input sizes
        # only within the same exact frozen plot profile. Never conflate both.
        from itertools import combinations
        for first, second in combinations(summaries, 2):
            a, b = first["variant"], second["variant"]
            same_plot = a["plot_profile"] == b["plot_profile"]
            same_size = a["requested_size"] == b["requested_size"]
            if same_plot == same_size:  # both changed, or neither changed
                continue
            contract_ok = len(first["plot_contract_ids"]) == len(second["plot_contract_ids"]) == 1
            if same_plot:
                contract_ok = contract_ok and first["plot_contract_ids"] == second["plot_contract_ids"]
            for metric in ("worker_seconds", "full_cycle_seconds"):
                ratios.append({"reference_variant": first["variant_id"], "candidate_variant": second["variant_id"],
                               "intended_variable": "input_size" if same_plot else "plot_profile", "metric": metric,
                               **(session_ratio(latencies[(first["variant_id"], metric)], latencies[(second["variant_id"], metric)],
                                                paired=True, seed=seed, resamples=resamples) if contract_ok else
                                  {"status": "unavailable", "ratio": None, "reason": "missing/inconsistent saved rendering contract for the declared comparison"}),
                               "limit": "reference/candidate work differs as declared; this is a workload cost ratio, not same-work hardware speedup"})
        first = next(iter(variants.values()))[0]
        reports.append({"scaling_control_id": identity, "device_label": first["device_label"], "pair": first["pair"],
                        "variants": summaries, "workload_cost_ratios": ratios,
                        "status": "observed_scaling_comparison" if len(summaries) > 1 else "single_variant_no_scaling_curve"})
    return {"groups": reports, "excluded_measured": excluded, "raw_journal": "scaling.jsonl.gz", "raw_attempts_pruned": False,
            "intended_variables": ["input_selection_size", "frozen_plot_profile"],
            "limits": ["scaling protocol only; source/library/backend/device/thread/process/thermal controls remain separate",
                       "per-row full-work cost includes fixed startup/output overhead, not inferred algorithmic complexity",
                       "selected points/empty filters/specs describe visible selection, not scientific utility or guaranteed SAA detection",
                       "sampled RSS can miss peaks; largest successful input is not a memory capacity guarantee",
                       "PNG bytes are observed output payload; no assumed radio, bitrate, transfer time or power"]}
