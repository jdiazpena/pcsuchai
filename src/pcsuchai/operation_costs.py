"""Exclusive dated receipts for complete API calls and external commands.

These costs are not scientific-job latency. Receipts live outside immutable
campaign/import/report payloads and cannot change their transfer inventories.
"""

from __future__ import annotations

import inspect
import base64
import gzip
import hashlib
import json
import math
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from .campaign_costs import cost_clock


def _commit(path: Path, value: dict) -> None:
    """Exclusively write and fsync small metadata, never replacing a receipt."""

    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class OperationCosts:
    """Retain an intent before work and a separate terminal cost after return.

    A missing terminal is unfinished/unknown, never a zero-cost success. Parent
    CPU includes its threads, not children. Actual clocks are acquired before
    receipt setup and immediately after the operation, so initial intent I/O is
    included; terminal receipt writing is outside the reported boundary.
    """

    def __init__(self, receipt_root, operation, *, scope, context, started=None):
        self.started = cost_clock() if started is None else started
        now = datetime.now(timezone.utc)
        if not operation or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in operation):
            raise ValueError("operation receipt name must be a safe lower-case identifier")
        self.directory = (Path(receipt_root).resolve() / now.strftime("%Y/%m/%d") /
                          f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{operation}-{uuid.uuid4().hex[:12]}")
        self.directory.mkdir(parents=True, exist_ok=False)
        self.intent = {"schema_version": 1, "operation_id": self.directory.name,
                       "operation": operation, "scope": scope, "started": self.started,
                       "context": context, "runtime": {"python_executable": sys.executable,
                       "python_version": platform.python_version(), "platform": platform.platform(),
                       "machine": platform.machine(), "pid": os.getpid()},
                       "source": "time.monotonic/time.process_time", "units": "seconds",
                       "cpu_scope": "recording_parent_process_all_threads_excluding_children"}
        _commit(self.directory / "intent.json", self.intent)

    def finish(self, *, status, ended=None, outcome=None, error=None, extra=None):
        """Close a returned/raised call without claiming scientific acceptance."""

        if status not in ("returned", "raised"):
            raise ValueError("operation terminal status must describe return or exception")
        ended = cost_clock() if ended is None else ended
        result = {"schema_version": 1, "operation_id": self.intent["operation_id"],
                  "status": status, "outcome": outcome, "error": error, "ended": ended,
                  "wall_seconds": ended["monotonic_seconds"] - self.started["monotonic_seconds"],
                  "parent_process_cpu_seconds": ended["process_cpu_seconds"] - self.started["process_cpu_seconds"],
                  "limit": "includes initial receipt setup; excludes own terminal receipt write; containing command/API/job scopes must not be added together",
                  "extra": extra}
        _commit(self.directory / "terminal.json", result)
        return {"directory": str(self.directory), "intent": "intent.json", "terminal": "terminal.json",
                "scope": self.intent["scope"], "status": status, "outcome": outcome,
                "wall_seconds": result["wall_seconds"],
                "parent_process_cpu_seconds": result["parent_process_cpu_seconds"]}


def measured_operation(operation, output_argument, *, input_argument=None):
    """Measure public output-producing calls after their device lock is held.

    Receipt storage is a dated sibling ``operation-costs/`` directory, outside
    all declared immutable inputs and the output payload. Original API artifacts
    remain untouched. Failure receipts survive even when no output was created.
    Returned dictionaries gain a receipt reference; exceptions are re-raised.
    """

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            started = cost_clock()
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            output = Path(bound.arguments[output_argument]).resolve()
            inputs = bound.arguments.get(input_argument, []) if input_argument else []
            inputs = list(inputs) if isinstance(inputs, (list, tuple)) else [inputs]
            inputs = [Path(value).resolve() for value in inputs]
            receipt_root = output.parent / "operation-costs"
            if receipt_root.is_relative_to(output) or any(receipt_root.is_relative_to(value) for value in inputs):
                raise ValueError("operation receipt storage must be outside immutable inputs/output")
            costs = OperationCosts(receipt_root, operation, scope="complete_locked_public_API_call",
                                   context={"input_paths": [str(path) for path in inputs], "output_path": str(output),
                                            "function": f"{function.__module__}.{function.__name__}",
                                            "lock_acquisition": "excluded; use external command clock for launch-through-exit"},
                                   started=started)
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                ended = cost_clock()
                try:
                    costs.finish(status="raised", ended=ended,
                                 error={"type": type(exc).__name__, "message": str(exc)})
                except BaseException as receipt_error:
                    exc.add_note(f"operation receipt could not be committed at {costs.directory}: {receipt_error}")
                raise
            ended = cost_clock()
            receipt = costs.finish(status="returned", ended=ended,
                                   outcome=result.get("status", result.get("passed")) if isinstance(result, dict) else None,
                                   extra={"returned_result": result} if isinstance(result, dict) else None)
            return {**result, "operation_cost": receipt} if isinstance(result, dict) else result

        return wrapped
    return decorate


def _finite_nonnegative(value):
    """Reject invalid/boolean clock readings while retaining genuine zero CPU."""

    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _validate_command_details(intent, terminal):
    """Audit optional launch/child-CPU subclocks without promoting their scope."""

    if intent["scope"] != "external_command_setup_launch_exit_and_raw_log_finalization":
        return
    extra = terminal.get("extra")
    if not isinstance(extra, dict):
        raise ValueError("external command lacks its explicit subclock availability")
    launch, cpu = extra.get("launch_through_exit"), extra.get("waited_children_cpu")
    if terminal["status"] == "returned" and (not isinstance(launch, dict) or not isinstance(cpu, dict)):
        raise ValueError("returned command lacks launch/exit or child CPU accounting")
    if launch is not None:
        start, end, wall = launch["started"]["monotonic_seconds"], launch["ended"]["monotonic_seconds"], launch["wall_seconds"]
        if (not all(_finite_nonnegative(value) for value in (start, end, wall))
                or not intent["started"]["monotonic_seconds"] <= start <= end <= terminal["ended"]["monotonic_seconds"]
                or abs(end - start - wall) > 1e-8
                or launch.get("scope") != "subprocess_Popen_to_wait_return_excluding_parent_log_finalization"):
            raise ValueError("command launch/exit subclock disagrees with containing cost")
    if cpu is not None:
        if cpu.get("status") not in ("available", "unavailable"):
            raise ValueError("unknown waited-child CPU availability")
        if cpu["status"] == "available":
            if (cpu.get("source") != "getrusage(RUSAGE_CHILDREN)_cumulative_difference"
                    or cpu.get("unit") != "seconds"
                    or cpu.get("scope") != "waited_children_and_descendants_accounted_by_kernel_not_individual_worker"):
                raise ValueError("waited-child CPU measurement contract disagrees")
            for metric in ("user_seconds", "system_seconds"):
                start, end, value = cpu["before"][metric], cpu["after"][metric], cpu[metric]
                if not all(_finite_nonnegative(v) for v in (start, end, value)) or end < start or abs(end - start - value) > 1e-8:
                    raise ValueError("waited-child CPU boundaries disagree")
    finalization = extra.get("raw_output_finalization_seconds")
    if finalization is not None and (not _finite_nonnegative(finalization) or finalization > terminal["wall_seconds"]):
        raise ValueError("command raw-output finalization clock is invalid")


def report_operation_costs(receipt_roots, output_dir):
    """Audit saved receipts into lossless raw records and outcome-separated tables.

    Never synthesize a terminal from intent times, sum containing scopes into
    deployment elapsed time, or classify a returned API as scientific acceptance.
    Original receipt bytes (including corruption) are retained base64 in gzip.
    No scientific models execute. Source/runtime/work drift is not normalized
    into a claimed hardware speedup; tables are descriptive exact-context costs.
    """

    from .run_lock import device_run_lock
    from .saved_attempts import _json_text
    with device_run_lock():
        roots = [Path(root).resolve() for root in receipt_roots]
        if not roots or len(roots) != len(set(roots)):
            raise ValueError("provide distinct operation receipt roots")
        destination = Path(output_dir).resolve()
        if any(destination.is_relative_to(root) for root in roots):
            raise ValueError("cost report must be outside immutable receipt roots")
        directories = set()
        for root in roots:
            if not root.is_dir():
                raise ValueError(f"operation receipt root is not a directory: {root}")
            for name in ("intent.json", "terminal.json"):
                directories.update(path.parent for path in root.rglob(name))
        rows = []
        for directory in sorted(directories):
            row = {"directory": str(directory), "status": "unfinished", "reason": "no committed terminal receipt",
                   "raw_intent_base64": None, "raw_terminal_base64": None,
                   "intent": None, "terminal": None}
            try:
                for name, key in (("intent.json", "intent"), ("terminal.json", "terminal")):
                    path = directory / name
                    if not path.exists() and not path.is_symlink():
                        continue
                    if path.is_symlink() or not any(path.resolve().is_relative_to(root) for root in roots):
                        raise ValueError("unsafe linked operation receipt; external bytes not read")
                    raw = path.read_bytes()
                    row[f"raw_{key}_base64"] = base64.b64encode(raw).decode("ascii")
                # A torn intent must not hide a recoverable terminal's bytes.
                for name, key in (("intent.json", "intent"), ("terminal.json", "terminal")):
                    if row[f"raw_{key}_base64"] is not None:
                        row[key] = _json_text(base64.b64decode(row[f"raw_{key}_base64"]).decode("utf-8"), str(directory / name))
                intent, terminal = row["intent"], row["terminal"]
                if (not isinstance(intent, dict) or type(intent.get("schema_version")) is not int
                        or intent["schema_version"] != 1 or intent.get("operation_id") != directory.name
                        or intent.get("scope") not in ("complete_locked_public_API_call", "external_command_setup_launch_exit_and_raw_log_finalization", "master_post_stdlib_bootstrap_to_return")
                        or intent.get("units") != "seconds" or intent.get("source") != "time.monotonic/time.process_time"
                        or intent.get("cpu_scope") != "recording_parent_process_all_threads_excluding_children"
                        or not isinstance(intent.get("operation"), str) or not intent["operation"]
                        or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in intent["operation"])
                        or not isinstance(intent.get("context"), dict) or not isinstance(intent.get("runtime"), dict)):
                    raise ValueError("invalid operation intent identity/schema/measurement contract")
                if terminal is not None:
                    if (type(terminal.get("schema_version")) is not int or terminal["schema_version"] != 1
                            or terminal.get("operation_id") != intent["operation_id"]
                            or terminal.get("status") not in ("returned", "raised")):
                        raise ValueError("invalid operation terminal identity/schema/outcome")
                    for clock, metric in (("monotonic_seconds", "wall_seconds"), ("process_cpu_seconds", "parent_process_cpu_seconds")):
                        start, end, value = intent["started"][clock], terminal["ended"][clock], terminal[metric]
                        if not all(_finite_nonnegative(v) for v in (start, end, value)) or end < start or abs(end - start - value) > 1e-8:
                            raise ValueError("operation clock boundaries disagree")
                    if terminal["status"] == "raised" and not isinstance(terminal.get("error"), dict):
                        raise ValueError("raised operation lacks its explicit error")
                    _validate_command_details(intent, terminal)
                    row.update(status=terminal["status"], reason=None)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
                row.update(status="invalid", reason=str(exc))
            rows.append(row)
        identities = {}
        for row in rows:
            intent = row["intent"]
            if isinstance(intent, dict) and isinstance(intent.get("operation_id"), str):
                identities.setdefault(intent["operation_id"], []).append(row)
        for duplicates in identities.values():
            if len(duplicates) > 1:
                for row in duplicates:
                    row.update(status="invalid", reason="duplicate operation identity would double-count calls")
        destination.mkdir(parents=True, exist_ok=False)
        tables = []
        counts = {status: sum(row["status"] == status for row in rows) for status in ("returned", "raised", "unfinished", "invalid")}
        with gzip.open(destination / "operation-costs.jsonl.gz", "xt", encoding="utf-8") as journal:
            for row in rows:
                journal.write(json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n")
                if row["status"] not in ("returned", "raised"):
                    continue
                intent, terminal = row["intent"], row["terminal"]
                context_hash = hashlib.sha256(json.dumps({"operation": intent["operation"], "scope": intent["scope"],
                    "context": intent["context"], "runtime": {key: value for key, value in intent["runtime"].items() if key != "pid"}},
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                tables.append({"operation_id": intent["operation_id"], "operation": intent["operation"], "scope": intent["scope"],
                    "recorded_context_id": context_hash, "status": row["status"], "outcome": terminal.get("outcome"),
                    "wall_seconds": terminal["wall_seconds"], "parent_process_cpu_seconds": terminal["parent_process_cpu_seconds"],
                    "command_details": terminal.get("extra") if intent["scope"].startswith("external_command") else None})
        result = {"schema_version": 1, "classification": "descriptive_operation_costs_not_scientific_acceptance_or_isolated_hardware_speed",
                  "counts": counts, "calls": tables, "raw_journal": "operation-costs.jsonl.gz", "raw_records_pruned": False,
                  "status": "incomplete_or_invalid" if counts["unfinished"] or counts["invalid"] else "saved_costs_audited" if rows else "no_saved_operation_receipts",
                  "limits": ["returned is an API/command outcome, not scientific acceptance", "missing terminals have unavailable cost, not zero",
                             "external commands contain API/job/stage clocks; never add containing scopes together", "recorded paths/recorder runtime are not a frozen scientific work signature; consult archived controls before comparison; no inferred speedup or precision"]}
        _commit(destination / "operation-cost-report.json", result)
        return {"report_path": str(destination / "operation-cost-report.json"), "status": result["status"], "counts": counts}
