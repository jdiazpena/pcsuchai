"""Reconcile durable attempts omitted by a checkpoint after abrupt termination.

Original attempts, partial products and malformed records are never replaced.
An independent reconciliation sidecar classifies each recoverable scheduled
slot. Missing commit timing is unavailable; recovery never invents elapsed time
or silently retries a consumed slot.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def reconcile_attempts(destination: Path, session: dict, validate_record) -> list[dict]:
    """Recover orphan terminal records or classify partial slots as interrupted.

    ``validate_record`` verifies retained successful scientific artifacts. A
    successful but damaged record becomes a failed recovery classification,
    with its original bytes preserved. Unknown or duplicate slot identities
    fail closed instead of scheduling replacement work. The caller already
    holds the inherited device lock, so a live old worker cannot be reconciled.
    """

    from .benchmark_suite import _atomic_write_json, _utc_text
    from .benchmark import sha256_file

    known = {item["run_id"] for item in session["execution_order"]}
    slots = {(item.get("kind"), item.get("round"), item.get("scenario")): item["run_id"]
             for item in session["execution_order"]}
    if len(slots) != len(session["execution_order"]):
        raise ValueError("duplicate scheduled slot in checkpoint")
    recovered = []
    allowed = set(session["scenarios"])
    for category, kind in (("runs", "measured"), ("warmups", "warmup")):
        for directory in sorted((destination / category).glob("*/*")):
            if not directory.is_dir() or directory.is_symlink() or directory.name in known:
                continue
            match = re.search(r"-r(\d+)-(.+)$", directory.name)
            if match is None or match[2] not in allowed:
                raise ValueError(f"cannot identify retained attempt slot: {directory}")
            round_number, scenario = int(match[1]), match[2]
            maximum = session["settings"].get("warmups") if kind == "warmup" else session["settings"].get("repeats")
            if round_number < 1 or (maximum is not None and round_number > maximum):
                raise ValueError(f"retained attempt is outside frozen schedule: {directory}")
            slot = (kind, round_number, scenario)
            if slot in slots:
                raise ValueError(f"multiple retained attempts occupy scheduled slot {slot}; originals preserved")
            original = directory / "run-record.json"
            intent_path = directory / "attempt-intent.json"
            reconciliation = directory / "reconciliation-record.json"
            if reconciliation.is_file():
                record = json.loads(reconciliation.read_text())
                if (record.get("kind"), record.get("round"), record.get("scenario"), record.get("run_id")) != (*slot, directory.name):
                    raise ValueError(f"reconciliation identity mismatch: {reconciliation}")
                for key, path in (("original_record_sha256", original), ("intent_sha256", intent_path)):
                    if record.get(key) and (not path.is_file() or sha256_file(path) != record[key]):
                        raise ValueError(f"previously reconciled original bytes changed: {path}")
                # A prior recovery may itself have lost its checkpoint commit.
                # Check scientific bytes again before accepting its status.
                if record["status"] == "complete":
                    validate_record(json.loads(original.read_text()))
            else:
                record = {"schema_version": 1, "run_id": directory.name, "kind": kind,
                          "round": round_number, "scenario": scenario,
                          "run_directory": str(directory), "status": "interrupted",
                          "started_utc": None, "finished_utc": None,
                          "reconciled_utc": _utc_text(), "reason": "abrupt termination before terminal commit",
                          "timing_status": "unavailable_uncommitted", "automatic_retry": False,
                          "original_record_path": str(original) if original.is_file() else None}
                if intent_path.is_file():
                    intent = json.loads(intent_path.read_text())
                    if (intent.get("kind"), intent.get("round"), intent.get("scenario"), intent.get("run_id")) != (*slot, directory.name):
                        raise ValueError(f"attempt intent identity mismatch: {intent_path}")
                    record.update(started_utc=intent.get("started_utc"), command=intent.get("command"),
                                  intent_path=str(intent_path), intent_sha256=sha256_file(intent_path))
                if original.is_file():
                    record["original_record_sha256"] = sha256_file(original)
                    try:
                        terminal = json.loads(original.read_text())
                        if not isinstance(terminal, dict):
                            raise ValueError("terminal record must be a JSON object")
                        if terminal.get("run_id") != directory.name or terminal.get("status") not in ("complete", "failed", "interrupted"):
                            raise ValueError("invalid terminal record identity/status")
                        if terminal.get("repeat", terminal.get("round")) != round_number:
                            raise ValueError("terminal record round differs from its scheduled slot")
                        if terminal.get("scenario", scenario) != scenario:
                            raise ValueError("terminal record scenario differs from its scheduled slot")
                        command = terminal["command"]
                        if not isinstance(command, list) or not all(isinstance(argument, str) for argument in command):
                            raise ValueError("terminal command must contain string arguments")
                        recorded_pair = f"{command[command.index('--orbit-backend') + 1]}-{command[command.index('--magnetic-backend') + 1]}"
                        if recorded_pair != scenario:
                            raise ValueError("terminal command differs from its scheduled backend pair")
                        if terminal["status"] == "complete":
                            validate_record(terminal)
                        record.update(status=terminal["status"], started_utc=terminal.get("started_utc"),
                                      finished_utc=terminal.get("finished_utc"), command=terminal.get("command"),
                                      reason="terminal record recovered after missing checkpoint commit")
                    except (ValueError, KeyError, OSError, RuntimeError, TypeError, IndexError) as exc:
                        record.update(status="failed", reason=f"damaged or invalid retained terminal record: {type(exc).__name__}: {exc}",
                                      failure_class="retained_product_integrity")
                _atomic_write_json(reconciliation, record)
            execution = {**record, "reconciliation_path": str(reconciliation),
                         "cooldown": {"status": "unknown_before_restart", "passed": False}}
            session["execution_order"].append(execution)
            if execution["status"] == "complete" and kind == "measured":
                session["scenarios"][scenario]["runs"].append({"run_id": directory.name, "record_path": str(original)})
            elif execution["status"] == "failed":
                session["failures"].append(execution)
            elif execution["status"] == "interrupted":
                session.setdefault("interruptions", []).append(execution)
            slots[slot] = directory.name
            known.add(directory.name)
            recovered.append(execution)
    return recovered
