"""Strict cross-device comparison of completed benchmark sessions."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def _signature(session: dict) -> dict:
    """Return only fields that must match for a valid device comparison."""

    return {
        "official": session.get("official"),
        "source_sha256": session["source"]["sha256"],
        "python_version": session["runtime"]["python_version"],
        "cpu_governor": session["runtime"].get("cpu_governor"),
        "packages": session["runtime"]["packages"],
        "settings": session["settings"],
        "inputs": {
            name: {"sha256": record["sha256"], "size_bytes": record["size_bytes"]}
            for name, record in session["inputs"].items()
        },
        "scenarios": sorted(session["scenarios"]),
    }


def compare_sessions(paths: list[str | Path], output_dir: str | Path) -> dict:
    """Validate comparability and emit combined machine-readable tables."""

    if len(paths) < 2:
        raise ValueError("at least two benchmark sessions are required")
    loaded = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        session = json.loads(path.read_text(encoding="utf-8"))
        loaded.append((path, session))
    labels = [session.get("device_label") for _, session in loaded]
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("sessions require unique, non-empty device labels")

    reference = _signature(loaded[0][1])
    mismatches = []
    for _, session in loaded:
        if session.get("status") != "complete":
            mismatches.append({"device": session.get("device_label"), "field": "status", "expected": "complete", "actual": session.get("status")})
        if not session.get("scientific_outputs_consistent"):
            mismatches.append({"device": session.get("device_label"), "field": "scientific_outputs_consistent", "expected": True, "actual": session.get("scientific_outputs_consistent")})
        if session.get("official") is not True:
            mismatches.append({"device": session.get("device_label"), "field": "official", "expected": True, "actual": session.get("official")})
        candidate = _signature(session)
        for field, expected in reference.items():
            if candidate[field] != expected:
                mismatches.append({"device": session["device_label"], "field": field, "expected": expected, "actual": candidate[field]})

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "comparable" if not mismatches else "not_comparable",
        "sessions": [{"device_label": session["device_label"], "path": str(path)} for path, session in loaded],
        "reference_signature": reference,
        "mismatches": mismatches,
    }

    if not mismatches:
        summary_path = destination / "device-comparison.csv"
        columns = [
            "device_label", "board_model", "machine", "scenario", "stage", "metric",
            "mean", "median", "standard_deviation", "minimum", "maximum", "p95",
        ]
        with summary_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for _, session in loaded:
                common = {
                    "device_label": session["device_label"],
                    "board_model": session["runtime"].get("board_model"),
                    "machine": session["runtime"].get("machine"),
                }
                for scenario, scenario_report in session["scenarios"].items():
                    whole = scenario_report["summary"]["external_wall_seconds"]
                    writer.writerow({**common, "scenario": scenario, "stage": "WHOLE_PROCESS", "metric": "external_wall_seconds", **whole})
                    for stage, metrics in scenario_report["summary"]["stages"].items():
                        for metric, values in metrics.items():
                            writer.writerow({**common, "scenario": scenario, "stage": stage, "metric": metric, **values})
        report["comparison_csv"] = str(summary_path)

    report_path = destination / "device-comparison.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
