"""Unique raw recovery-trace costs, never duplicated checkpoint references."""

from __future__ import annotations

import base64
import gzip
import json
import math

from .saved_attempts import _json_text
from .benchmark import sha256_file


def _finite(value):
    """Validate nonnegative finite costs without accepting booleans."""

    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def report_recovery_costs(experiments, destination):
    """Inventory actual trace files, verify receipts and preserve partial costs.

    Baseline/initial_cooldown/recovery_records can refer to one acquisition:
    checkpoint references are not summed. Raw trace hashes bind each exclusive
    receipt; absent historical/partial costs stay unavailable, not estimated
    from the trace's last timestamp. Original raw traces stay in the campaign.
    """

    reports, issues = [], []
    with gzip.open(destination / "recovery-costs.jsonl.gz", "xt", encoding="utf-8") as journal:
        for experiment in experiments:
            root = experiment["root"]
            traces = []
            for path in sorted(root.glob("sessions/session-*/block-*/recovery/*.csv*")):
                if not (path.name.endswith(".csv") or path.name.endswith(".csv.gz")):
                    continue
                if path.suffix != ".gz" and path.with_name(path.name + ".gz").exists():
                    continue  # Prefer closed copy; do not delete either original.
                receipt_path = path.with_name(path.name + ".receipt.json")
                row = {"experiment_id": experiment["identity"], "device_label": experiment["state"].get("device_label"),
                       "trace": path.relative_to(root).as_posix(), "status": "unavailable",
                       "receipt": None, "raw_receipt_base64": None, "reason": "no committed acquisition cost receipt"}
                try:
                    if path.is_symlink() or receipt_path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not receipt_path.resolve().is_relative_to(root.resolve()):
                        raise ValueError("unsafe linked recovery cost path; external bytes not read")
                    if receipt_path.is_file():
                        raw = receipt_path.read_bytes()
                        row["raw_receipt_base64"] = base64.b64encode(raw).decode("ascii")
                        receipt = _json_text(raw.decode("utf-8"), str(receipt_path))
                        if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
                            raise ValueError("invalid recovery cost schema")
                        if (receipt.get("scope") != "thermal_acquisition_call_including_journal_compression_and_trace_hash"
                                or receipt.get("source") != "time.monotonic/time.process_time"
                                or receipt.get("units") != "seconds"):
                            raise ValueError("recovery cost units/source/scope disagree")
                        if receipt.get("trace_name") != path.name or receipt.get("trace_sha256") != sha256_file(path):
                            raise ValueError("recovery receipt does not bind retained trace bytes")
                        for clock, metric in (("monotonic_seconds", "wall_seconds"), ("process_cpu_seconds", "parent_process_cpu_seconds")):
                            start, end, value = receipt["started"][clock], receipt["ended"][clock], receipt.get(metric)
                            if not all(_finite(v) for v in (start, end, value)) or end < start or abs(end - start - value) > 1e-8:
                                raise ValueError("recovery cost clock boundaries disagree")
                        if receipt.get("result_status") not in (
                                "baseline_acquired", "stable", "sensor_unavailable",
                                "maximum_wait_reached", "cancelled", "clock_invalid"):
                            raise ValueError("unknown recovery condition outcome")
                        if type(receipt.get("passed")) is not bool or receipt["passed"] != (receipt.get("result_status") in ("baseline_acquired", "stable")):
                            raise ValueError("recovery condition outcome disagrees")
                        row.update(status="available", receipt=receipt, reason=None)
                except (OSError, ValueError, KeyError, TypeError, OverflowError, AttributeError) as exc:
                    row.update(status="invalid", reason=str(exc))
                    issues.append({"experiment_id": experiment["identity"], "trace": row["trace"],
                                   "classification": "invalid_recovery_cost_evidence", "error": str(exc)})
                journal.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
                traces.append({key: value for key, value in row.items() if key != "raw_receipt_base64"})
            available = [row["receipt"] for row in traces if row["status"] == "available"]
            complete = bool(traces) and len(available) == len(traces)
            reports.append({"experiment_id": experiment["identity"], "traces": traces,
                            "trace_count": len(traces), "available_cost_count": len(available),
                            "unavailable_or_invalid_cost_count": len(traces) - len(available),
                            "status": "available" if complete else "no_saved_recovery_acquisitions" if not traces else "incomplete",
                            "total_acquisition_wall_seconds": sum(row["wall_seconds"] for row in available) if complete else None,
                            "total_acquisition_parent_cpu_seconds": sum(row["parent_process_cpu_seconds"] for row in available) if complete else None,
                            "passed_conditions": sum(row["passed"] for row in available),
                            "unmet_conditions": sum(not row["passed"] for row in available)})
    return {"experiments": reports, "issues": issues, "raw_journal": "recovery-costs.jsonl.gz", "raw_records_pruned": False,
            "limit": "unique acquisition calls contained in block/API clocks; do not add them again to campaign totals; missing legacy/partial receipts never imply zero recovery cost"}
