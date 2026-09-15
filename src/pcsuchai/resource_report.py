"""Stage resource deltas and repeated counters reconstructed from saved raw data."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from .counters import matched_ipc, parse_counter_text


STAGE_UNITS = {
    "read_bytes": "bytes", "write_bytes": "bytes", "read_chars": "bytes", "write_chars": "bytes",
    "voluntary_context_switches": "count", "involuntary_context_switches": "count",
    "minor_page_faults": "count", "major_page_faults": "count",
}


def _nonnegative(value):
    """Accept genuine zero and exact arbitrary-size integers, never booleans."""

    return type(value) is int and value >= 0 or type(value) is float and math.isfinite(value) and value >= 0


def _summary(values):
    """Descriptive counts with exact integer totals/median, without latency units."""

    ordered = sorted(values)
    if not ordered:
        return {"available_count": 0, "minimum": None, "maximum": None, "sum": None,
                "median_exact": None}
    middle = len(ordered) // 2
    median = (Fraction(ordered[middle - 1]) + Fraction(ordered[middle])) / 2 if len(ordered) % 2 == 0 else Fraction(ordered[middle])
    total = sum(ordered)
    return {"available_count": len(ordered), "minimum": ordered[0], "maximum": ordered[-1],
            "sum": total if type(total) is int or math.isfinite(total) else None,
            "median_exact": {"numerator": str(median.numerator), "denominator": str(median.denominator)},
            "uncertainty": "descriptive observed jobs; no independent hot-loop confidence interval"}


def _identity(attempt):
    """Separate work, device, backend, warmup/measured phase and outcome."""

    return (attempt["cohort_id"], attempt["device_label"], attempt["pair"], attempt["kind"], attempt["status"])


def _labels(key):
    """Expand the common table identity without dropping failed outcomes."""

    return dict(zip(("cohort_id", "device_label", "pair", "kind", "status"), key[:5]))


def report_resources(stages, attempts, destination):
    """Read verified stage products and each attempt's own perf text, never perf.

    Counter values in run-record metadata are NOT numerical evidence: raw text
    is reparsed with the frozen group and coverage policy. Missing/denied/poor
    values remain explicit. Failed/excluded/warmup observations stay in tables,
    but only checked measured complete jobs supply accepted-value statistics.
    All source counter bytes (including malformed lines) are retained losslessly
    in a compressed journal. Stage raw records already reside in stages.jsonl.gz.
    """

    indexed = {(a["experiment_id"], a["run_id"]): a for a in attempts}
    stage_counts = Counter()
    stage_groups = defaultdict(lambda: {"values": [], "accepted": [], "statuses": Counter(), "sessions": Counter()})
    with gzip.open(stages, "rt", encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            attempt = indexed[(row["experiment_id"], row["run_id"])]
            stage_counts[(attempt["experiment_id"], attempt["run_id"])] += 1
            for metric, unit in STAGE_UNITS.items():
                value = row["stage_record"].get(metric)
                group = stage_groups[(*_identity(attempt), row["stage_record"]["stage"], metric, unit)]
                status = "available" if _nonnegative(value) else "unavailable" if value is None else "invalid_saved_value"
                group["statuses"][status] += 1
                group["sessions"][attempt["session_id"]] += 1
                if status == "available":
                    group["values"].append(value)
                    if attempt["kind"] == "measured" and attempt["status"] == "complete" and not attempt["issues"] and attempt["cohort_id"]:
                        group["accepted"].append(value)
    counters, counter_groups, issues = [], defaultdict(lambda: {"values": [], "accepted": [], "statuses": Counter(), "quality": Counter(), "sessions": Counter()}), []
    with gzip.open(destination / "hardware-counters.jsonl.gz", "xt", encoding="utf-8") as journal:
        for attempt in attempts:
            controls = attempt.get("controls") or {}
            observation = controls.get("observation") or {}
            requested = observation.get("counter_groups") or [None]
            requested = requested[0] if len(requested) == 1 else None
            recorded = attempt.get("hardware_counters")
            if requested is None and recorded is None:
                continue  # This job was never a counter experiment.
            requested = list(requested) if isinstance(requested, (tuple, list)) else None
            point = {"experiment_id": attempt["experiment_id"], "run_id": attempt["run_id"],
                     **_labels(_identity(attempt)), "requested_events": requested, "collection_status": "unavailable",
                     "recorded_metadata": recorded, "accounting": None, "raw_bytes_base64": None,
                     "source": "retained perf stat aggregate text", "scope": "whole_analysis_process_and_inherited_children",
                     "reason": None, "ipc": {"status": "unavailable", "value": None, "unit": "instructions_per_cycle"}}
            directory = Path(attempt["directory"])
            path = directory / "perf-stat.csv.gz"
            if not path.exists():
                path = directory / "perf-stat.csv"
            try:
                if directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                    raise ValueError("unsafe linked counter path; external bytes not read")
                if not path.is_file():
                    point["reason"] = recorded.get("reason", "counter text not retained") if isinstance(recorded, dict) else "counter text not retained"
                else:
                    opener = gzip.open if path.suffix == ".gz" else open
                    with opener(path, "rb") as source:
                        raw = source.read()
                    point.update(raw_bytes_base64=base64.b64encode(raw).decode("ascii"),
                                 raw_sha256=hashlib.sha256(raw).hexdigest(), raw_size_bytes=len(raw))
                    if not requested:
                        raise ValueError("frozen simultaneous counter group unavailable")
                    accounting = parse_counter_text(raw.decode("utf-8", errors="replace"), source_path=path.name,
                                                     minimum_coverage_percent=observation.get("minimum_counter_coverage_percent", 95.))
                    point["accounting"] = accounting
                    exact_group = sorted(e["event"] for e in accounting["events"]) == sorted(requested)
                    acceptable = exact_group and not accounting["unparsed_lines"] and all(e["availability"] == "available" and e["quality"] == "acceptable" for e in accounting["events"])
                    point["collection_status"] = "acceptable" if acceptable else "unavailable_or_poor_coverage"
                    point["ipc"] = matched_ipc(accounting, simultaneous_group=exact_group and not accounting["unparsed_lines"])
                    if not exact_group:
                        point["reason"] = "retained events differ from frozen simultaneous group"
                    events = accounting["events"]
                    # Missing requested events have unavailable slots; never 0.
                    for missing in Counter(requested) - Counter(e["event"] for e in events):
                        events = [*events, {"event": missing, "scope": "unknown", "unit": "unknown", "availability": "missing_requested_event", "quality": "unavailable", "reported_value": None}]
                    for event in events:
                        key = (*_identity(attempt), event["event"], event["scope"], event["unit"])
                        group = counter_groups[key]
                        group["statuses"][event["availability"]] += 1
                        group["quality"][event["quality"]] += 1
                        group["sessions"][attempt["session_id"]] += 1
                        if _nonnegative(event["reported_value"]):
                            group["values"].append(event["reported_value"])
                            if acceptable and attempt["kind"] == "measured" and attempt["status"] == "complete" and not attempt["issues"] and attempt["cohort_id"]:
                                group["accepted"].append(event["reported_value"])
            except (OSError, EOFError, ValueError, TypeError, OverflowError) as exc:
                point.update(collection_status="invalid_saved_counter_evidence", reason=str(exc))
                issues.append({"experiment_id": attempt["experiment_id"], "run_id": attempt["run_id"],
                               "classification": "invalid_saved_counter_evidence", "error": str(exc)})
            if point["accounting"] is None and requested:
                for event in requested:
                    group = counter_groups[(*_identity(attempt), event, "unknown", "unknown")]
                    group["statuses"][point["collection_status"]] += 1
                    group["quality"]["unavailable"] += 1
                    group["sessions"][attempt["session_id"]] += 1
            journal.write(json.dumps(point, separators=(",", ":"), allow_nan=False) + "\n")
            counters.append({key: value for key, value in point.items() if key not in ("accounting", "raw_bytes_base64", "recorded_metadata")})
    return {"stage_attempts": [{"experiment_id": a["experiment_id"], "run_id": a["run_id"],
                               "saved_stage_count": stage_counts[(a["experiment_id"], a["run_id"])],
                               "availability": "available" if stage_counts[(a["experiment_id"], a["run_id"])] else "unavailable_no_saved_stages"} for a in attempts],
            "stage_tables": [{**_labels(key), "stage": key[5], "metric": key[6], "unit": key[7],
                              "source": "saved BenchmarkRecorder psutil/rusage stage endpoint deltas",
                              "scope": "analysis_process_stage; Linux I/O may include waited-for children",
                              "availability": dict(value["statuses"]), "session_observation_counts": dict(value["sessions"]),
                              "observed": _summary(value["values"]), "accepted_measured": _summary(value["accepted"])} for key, value in stage_groups.items()],
            "counter_tables": [{**_labels(key), "event": key[5], "event_scope": key[6], "unit": key[7],
                                "availability": dict(value["statuses"]), "quality": dict(value["quality"]),
                                "session_observation_counts": dict(value["sessions"]), "observed_reported_values": _summary(value["values"]),
                                "accepted_measured_reported_values": _summary(value["accepted"])} for key, value in counter_groups.items()],
            "counter_attempts": counters, "issues": issues, "raw_counter_journal": "hardware-counters.jsonl.gz",
            "limits": ["stage deltas exclude parent retention/setup; sampled observation counters remain separate",
                       "storage-layer bytes are not logical read/write chars, downlink bytes or SD-card wear",
                       "perf raw integer counts stay exact; enabled time/scaled values are estimates from rounded coverage",
                       "IPC uses matched same-group scopes/windows; ARMv6/AArch64 instruction streams are not universal efficiency scores"],
            "raw_records_pruned": False}
