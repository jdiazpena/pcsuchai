"""Observed job-context temperature associations and early/late latency windows."""

from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict

from .reading_statistics import ReadingTrend
from .session_statistics import session_statistics


def _finite(value) -> bool:
    """Require a finite scalar, excluding missing values and booleans."""

    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


class Association:
    """Online centred covariance, not independent-job inference or causal fit."""

    def __init__(self):
        """Initialize centred moments without retaining the source point list."""
        self.count = 0
        self.mean_x = self.mean_y = self.xx = self.yy = self.xy = 0.

    def add(self, temperature, latency):
        """Include one checked measured job's mean temperature and positive time."""

        self.count += 1
        dx, dy = temperature - self.mean_x, latency - self.mean_y
        self.mean_x += dx / self.count
        self.mean_y += dy / self.count
        self.xx += dx * (temperature - self.mean_x)
        self.yy += dy * (latency - self.mean_y)
        self.xy += dx * (latency - self.mean_y)

    def report(self):
        """Expose undefined constant-temperature fits and correlated-job limits."""

        available = self.count >= 3 and self.xx > 0
        return {"status": "descriptive_association" if available else "unavailable",
                "jobs": self.count, "slope_seconds_per_celsius": self.xy / self.xx if available else None,
                "pearson_r": self.xy / math.sqrt(self.xx * self.yy) if available and self.yy > 0 else None,
                "mean_temperature_c": self.mean_x if self.count else None,
                "mean_latency_seconds": self.mean_y if self.count else None,
                "uncertainty": "unavailable: exploratory correlated jobs; no independent-job or causal confidence interval",
                "limit": "temperature/cache/order/frequency/background work are confounded; association is not a causal thermal effect"}


def report_thermal_performance(observations, attempts, destination, *, window_seconds=300., seed=1729, resamples=2000):
    """Reconstruct every job context; never interpolate missing sensor readings.

    The sampler applies its saved context label after acquisitions, so these
    samples are not atomic worker-execution bounds or continuous exposure.
    Early/late comparisons require disjoint complete context-time spans and
    remain descriptive, even if a temperature window appeared flat elsewhere.
    """

    if not _finite(window_seconds) or window_seconds <= 0:
        raise ValueError("performance window must be positive and finite")
    indexed = {(item["experiment_id"], item["run_id"]): item for item in attempts}
    temperatures, contexts = defaultdict(dict), {}
    with gzip.open(observations, "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            fields = row.get("raw_csv_fields", {})
            identity = (row["experiment_id"], fields.get("run_id"))
            attempt = indexed.get(identity)
            if attempt is None or fields.get("phase") != attempt["kind"]:
                continue
            key = (*identity, fields.get("segment_id"))
            try:
                elapsed = float(fields.get("campaign_elapsed_seconds"))
            except (TypeError, ValueError):
                elapsed = None
            if _finite(elapsed):
                context = contexts.setdefault(key, {"first_context_elapsed_seconds": elapsed,
                                                     "last_context_elapsed_seconds": elapsed, "clock_regressions": 0})
                context["clock_regressions"] += elapsed < context["last_context_elapsed_seconds"]
                context["last_context_elapsed_seconds"] = elapsed
            board = row.get("observations", {}).get("board", {})
            reading = board.get("soc_temperature_c") if isinstance(board, dict) else None
            if not isinstance(reading, dict):
                reading = {"status": "missing_saved_sensor_observation", "value": None}
            if reading.get("unit") != "degrees_Celsius" or reading.get("scope") != "board_soc":
                reading = {**reading, "status": "missing_or_invalid_temperature_unit_or_scope"}
            if reading.get("status") == "available" and (not _finite(reading.get("value")) or not _finite(reading.get("monotonic_seconds"))):
                reading = {**reading, "status": "malformed_available_temperature"}
            sensor = (*key, reading.get("source"), reading.get("scope"), reading.get("unit"))
            if sensor not in temperatures[identity]:
                temperatures[identity][sensor] = ReadingTrend()
            temperatures[identity][sensor].add(reading)
    fits, phase_values, temporal_groups = {}, defaultdict(lambda: defaultdict(list)), defaultdict(list)
    with gzip.open(destination / "thermal-performance.jsonl.gz", "xt", encoding="utf-8") as journal:
        for identity, attempt in indexed.items():
            matching = list(temperatures.get(identity, {}).items())
            if not matching:
                matching = [((*identity, None, None, None, None), ReadingTrend())]
            for key, trend in matching:
                sampled = trend.report()
                context = contexts.get(key[:3], {})
                usable = attempt["status"] == "complete" and not attempt["issues"] and attempt["cohort_id"] is not None
                point = {"experiment_id": identity[0], "run_id": identity[1], "segment_id": key[2],
                         "cohort_id": attempt["cohort_id"], "device_label": attempt["device_label"], "pair": attempt["pair"],
                         "kind": attempt["kind"], "status": attempt["status"], "recorded_status": attempt.get("recorded_status"),
                         "source": key[3], "scope": key[4], "unit": key[5], "sampled_temperature": sampled,
                         "context": context, "worker_seconds": attempt["worker_seconds"], "full_cycle_seconds": attempt["full_cycle_seconds"],
                         "scientifically_usable": bool(usable),
                         "usable_for_measured_association": bool(usable and attempt["kind"] == "measured" and sampled["numeric_sample_count"] and not sampled["clock_regressions"])}
                journal.write(json.dumps(point, separators=(",", ":"), allow_nan=False) + "\n")
                for metric in ("worker_seconds", "full_cycle_seconds"):
                    latency = point[metric]
                    if not usable or not _finite(latency) or latency <= 0:
                        continue
                    phase_key = (attempt["cohort_id"], attempt["device_label"], attempt["pair"], attempt["kind"], metric)
                    # Phase timings count each job once, independently of sensor channels.
                    if key == matching[0][0]:
                        phase_values[phase_key][attempt["session_id"]].append(latency)
                    if point["usable_for_measured_association"]:
                        fit_key = (attempt["cohort_id"], attempt["device_label"], attempt["pair"], key[3], key[4], key[5], metric)
                        if fit_key not in fits:
                            fits[fit_key] = Association()
                        fits[fit_key].add(sampled["mean"], latency)
                if attempt["kind"] == "measured" and key[2] is not None and context and not context["clock_regressions"] and key == matching[0][0]:
                    temporal_groups[(identity[0], attempt["block_path"], key[2], attempt["cohort_id"], attempt["pair"], attempt["device_label"])].append((attempt, context))
    windows = []
    for key, jobs in temporal_groups.items():
        first = min(context["first_context_elapsed_seconds"] for _, context in jobs)
        last = max(context["last_context_elapsed_seconds"] for _, context in jobs)
        sufficient = last - first >= 2 * window_seconds
        entry = {"experiment_id": key[0], "block_path": key[1], "segment_id": key[2],
                 "cohort_id": key[3], "pair": key[4], "device_label": key[5],
                 "status": "descriptive_disjoint_context_windows" if sufficient else "unavailable",
                 "window_seconds": window_seconds, "observed_context_span_seconds": last - first, "metrics": {}}
        if sufficient:
            selected = {"initial": [], "late": []}
            for attempt, context in jobs:
                if context["last_context_elapsed_seconds"] <= first + window_seconds:
                    selected["initial"].append(attempt)
                elif context["first_context_elapsed_seconds"] >= last - window_seconds:
                    selected["late"].append(attempt)
            entry["outcomes"] = {name: {"started": len(values), "complete_usable": sum(item["status"] == "complete" and not item["issues"] for item in values),
                                      "failed_or_interrupted": sum(item["status"] in ("failed", "interrupted") for item in values),
                                      "excluded": sum(bool(item["issues"]) for item in values)} for name, values in selected.items()}
            for metric in ("worker_seconds", "full_cycle_seconds"):
                phase = {"initial": defaultdict(list), "late": defaultdict(list)}
                for name, values in selected.items():
                    for attempt in values:
                        value = attempt[metric]
                        if attempt["status"] == "complete" and not attempt["issues"] and _finite(value) and value > 0:
                            phase[name][attempt["session_id"]].append(value)
                entry["metrics"][metric] = {name: session_statistics(dict(values), seed=seed, resamples=resamples) for name, values in phase.items()}
        windows.append(entry)
    return {"associations": [{"cohort_id": key[0], "device_label": key[1], "pair": key[2], "source": key[3],
                               "scope": key[4], "unit": key[5], "metric": key[6], **fit.report()} for key, fit in fits.items()],
            "phase_latency": [{"cohort_id": key[0], "device_label": key[1], "pair": key[2], "kind": key[3], "metric": key[4],
                               "statistics": session_statistics(dict(values), seed=seed, resamples=resamples)} for key, values in phase_values.items()],
            "early_late_windows": windows, "raw_journal": "thermal-performance.jsonl.gz", "raw_attempts_pruned": False,
            "limit": "sampled job contexts, not atomic worker bounds/exposure; early/late or warmup differences do not prove equilibrium, sustained stationarity or causal temperature dependence"}
