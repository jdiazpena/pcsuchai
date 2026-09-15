"""Saved API-segment costs with failed/partial journals and explicit boundaries."""

from __future__ import annotations

import base64
import gzip
import json
import math

from .saved_attempts import _json
from .storage import _nonnegative


def _phase_json(line):
    """Reject duplicate keys, non-finite literals and overflowing JSON floats."""

    def invalid(value):
        raise ValueError(f"non-finite JSON literal: {value}")
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
            raise ValueError("overflowing JSON float")
        return value
    return json.loads(line, parse_constant=invalid, object_pairs_hook=unique, parse_float=finite)


def report_campaign_costs(experiments, attempts, destination) -> dict:
    """Audit total/phase clocks, preserving every raw line and unknown legacy cost.

    Totals are API-active segments, not UTC elapsed time across pauses/reboots.
    Phases are their children, not additive to total or to included job cycles.
    Corrupt/missing receipts cannot supply throughput; valid jobs exclude warmups,
    failed work and scientifically excluded work. Child CPU is not parent CPU.
    """

    reports, issues = [], []
    with gzip.open(destination / "campaign-costs.jsonl.gz", "xt", encoding="utf-8") as journal:
        for experiment in experiments:
            identity, root = experiment["identity"], experiment["root"]
            segments = []
            for directory in sorted((root / "segments").glob("*")):
                if not directory.is_dir():
                    continue
                row = {"experiment_id": identity, "segment_id": directory.name, "status": "unavailable",
                       "total": None, "phase_count": 0, "phase_wall_seconds": None,
                       "unclassified_orchestration_wall_seconds": None}
                phases, errors = [], []
                path = directory / "costs.jsonl"
                total_path = directory / "segment-cost.json"
                if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()) or path.is_symlink() or total_path.is_symlink():
                    row.update(status="invalid", issues=["unsafe linked cost path; external bytes not read"])
                    segments.append(row)
                    issues.append({"experiment_id": identity, "segment_id": directory.name,
                                   "classification": "invalid_campaign_cost_evidence", "error": row["issues"][0]})
                    continue
                if path.exists():
                    with path.open("rb") as source:
                        for number, line in enumerate(source, 1):
                            value = None
                            try:
                                value = _phase_json(line)
                                if not isinstance(value, dict):
                                    raise ValueError("phase is not an object")
                                if not _nonnegative(value.get("wall_seconds")) or not _nonnegative(value.get("parent_process_cpu_seconds")):
                                    raise ValueError("phase clocks missing, non-finite or negative")
                                phases.append(value)
                            except (ValueError, TypeError, UnicodeError) as exc:
                                errors.append(f"phase line {number}: {exc}")
                                value = None
                            journal.write(json.dumps({"experiment_id": identity, "segment_id": directory.name,
                                                      "line": number, "raw_line_base64": base64.b64encode(line).decode("ascii"),
                                                      "parsed_phase": value},
                                                     separators=(",", ":"), allow_nan=False) + "\n")
                if total_path.exists():
                    try:
                        total = _json(total_path)
                        if not isinstance(total, dict) or type(total.get("schema_version")) is not int or total["schema_version"] != 1 or not _nonnegative(total.get("wall_seconds")) or not _nonnegative(total.get("parent_process_cpu_seconds")):
                            raise ValueError("invalid total receipt")
                        if type(total.get("phase_records")) is not int or total["phase_records"] != len(phases):
                            raise ValueError("phase journal count differs from committed total")
                        last = total["started"]["monotonic_seconds"]
                        if not _nonnegative(last):
                            raise ValueError("invalid segment start clock")
                        for index, phase in enumerate(phases, 1):
                            start, end = phase["started"]["monotonic_seconds"], phase["ended"]["monotonic_seconds"]
                            if not _nonnegative(start) or not _nonnegative(end) or start < last or end < start or phase.get("index") != index or abs(end - start - phase["wall_seconds"]) > 1e-8:
                                raise ValueError("phase clocks overlap/regress or boundaries disagree")
                            last = end
                            cpu_start, cpu_end = phase["started"]["process_cpu_seconds"], phase["ended"]["process_cpu_seconds"]
                            if not _nonnegative(cpu_start) or not _nonnegative(cpu_end) or cpu_end < cpu_start or abs(cpu_end - cpu_start - phase["parent_process_cpu_seconds"]) > 1e-8:
                                raise ValueError("phase CPU boundaries disagree")
                        ending = total["ended"]["monotonic_seconds"]
                        if not _nonnegative(ending) or ending < last or abs(ending - total["started"]["monotonic_seconds"] - total["wall_seconds"]) > 1e-8:
                            raise ValueError("total boundaries disagree with phase clocks")
                        cpu_start, cpu_end = total["started"]["process_cpu_seconds"], total["ended"]["process_cpu_seconds"]
                        if not _nonnegative(cpu_start) or not _nonnegative(cpu_end) or cpu_end < cpu_start or abs(cpu_end - cpu_start - total["parent_process_cpu_seconds"]) > 1e-8:
                            raise ValueError("total CPU boundaries disagree")
                        row.update(total=total, phase_count=len(phases), phase_wall_seconds=sum(phase["wall_seconds"] for phase in phases))
                        row["unclassified_orchestration_wall_seconds"] = total["wall_seconds"] - row["phase_wall_seconds"]
                        row["status"] = "available" if not errors else "invalid"
                    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
                        errors.append(str(exc))
                        row["status"] = "invalid"
                row["issues"] = errors
                issues.extend({"experiment_id": identity, "segment_id": directory.name, "classification": "invalid_campaign_cost_evidence", "error": error} for error in errors)
                segments.append(row)
            valid = sum(item["experiment_id"] == identity and item["kind"] == "measured" and item["status"] == "complete" and not item["issues"] for item in attempts)
            available = bool(segments) and all(row["status"] == "available" for row in segments)
            wall = sum(row["total"]["wall_seconds"] for row in segments) if available else None
            reports.append({"experiment_id": identity, "segments": segments, "status": "available" if available else "incomplete_or_unavailable",
                            "valid_scheduled_jobs": valid, "active_API_wall_seconds": wall,
                            "valid_jobs_per_active_API_second": valid / wall if wall else None,
                            "limit": "includes setup/validation/blocks/finalization, excludes pauses, launcher/lock and offline report/export; validation-reference jobs are not scheduled completions"})
    return {"experiments": reports, "issues": issues, "raw_journal": "campaign-costs.jsonl.gz", "raw_records_pruned": False}
