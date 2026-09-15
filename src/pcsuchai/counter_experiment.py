"""Capability-aware grouped perf collection for complete repeated jobs."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .counters import event_scope, matched_ipc, parse_counter_records
from .run_lock import inherited_lock_fds


def counter_command(command: list[str], group: tuple[str, ...], output: Path) -> list[str]:
    """Count a small simultaneous event group around one entire analysis child."""

    if not group or any(not isinstance(event, str) or not event or event.startswith("-") or any(character in event for character in ",{}\r\n") for event in group):
        raise ValueError("counter group must contain individual valid perf event names")
    if len({event_scope(event) for event in group}) != 1:
        raise ValueError("counter group must use compatible user/kernel scopes")
    return ["perf", "stat", "--no-scale", "--no-big-num", "-x", ";", "-o", str(output),
            "-e", "{" + ",".join(group) + "}", "--", *command]


def read_group_result(path: Path, group: tuple[str, ...], minimum_coverage_percent: float) -> dict:
    """Retain raw accounting/quality; IPC requires a matched simultaneous group."""

    report = parse_counter_records(path, minimum_coverage_percent=minimum_coverage_percent)
    acceptable = bool(group) and sorted(event["event"] for event in report["events"]) == sorted(group) and not report["unparsed_lines"] and all(
        event["availability"] == "available" and event["quality"] == "acceptable" for event in report["events"]
    )
    return {"status": "acceptable" if acceptable else "unavailable_or_poor_coverage",
            "requested_events": list(group), "accounting": report,
            "ipc": matched_ipc(report, simultaneous_group=acceptable), "raw_path": str(path),
            "scope": "whole_analysis_process_and_inherited_children", "unit_contract": "per-event units in accounting"}


def probe_counter_group(group: tuple[str, ...], directory: Path, environment: dict[str, str],
                        minimum_coverage_percent: float = 95.0) -> dict:
    """Probe actual permissions/support before selecting perf or basic timing.

    Event listings alone do not prove that a counter can be opened. Save a real
    grouped stat probe and tool/event definitions, without changing permissions
    or perf_event_paranoid. Probe work precedes warm-ups and thermal recovery.
    """

    from .benchmark_suite import _atomic_write_json
    from .retention import compress_retained_file
    directory.mkdir(parents=True, exist_ok=False)
    report = {"captured_utc": datetime.now(timezone.utc).isoformat(), "kernel": platform.release(),
              "requested_events": list(group), "event_scopes": [event_scope(event) for event in group],
              "status": "unsupported", "reason": "perf executable not found", "raw_files": []}
    counter_command([sys.executable, "-c", "sum(range(100000))"], group, directory / "probe.csv")
    try:
        report["perf_event_paranoid"] = Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()
    except OSError as exc:
        report["perf_event_paranoid"] = {"status": "unavailable", "reason": str(exc)}
    if shutil.which("perf"):
        commands = {
            "version": ["perf", "--version"],
            "definitions": ["perf", "list", "--details"],
            "probe": counter_command([sys.executable, "-c", "sum(range(100000))"], group, directory / "probe.csv"),
        }
        report["commands"] = commands
        for name, command in commands.items():
            stdout_path, stderr_path = directory / f"{name}.stdout.log", directory / f"{name}.stderr.log"
            try:
                with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                    completed = subprocess.run(command, env=environment, stdout=stdout, stderr=stderr,
                                               timeout=30, check=False, pass_fds=inherited_lock_fds(environment))
                report[f"{name}_return_code"] = completed.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                report[f"{name}_error"] = f"{type(exc).__name__}: {exc}"
        raw = directory / "probe.csv"
        if raw.exists():
            report["probe_result"] = read_group_result(raw, group, minimum_coverage_percent)
        if report.get("probe_return_code") == 0 and report.get("probe_result", {}).get("status") == "acceptable":
            report.update(status="acceptable", reason=None)
        else:
            stderr = (directory / "probe.stderr.log").read_text(errors="replace") if (directory / "probe.stderr.log").exists() else ""
            report.update(status="denied" if any(word in stderr.lower() for word in ("permission", "access", "paranoid")) else "unavailable",
                          reason=stderr[-4000:] or report.get("probe_error") or "group unavailable, not counted, or below coverage threshold")
        for path in sorted(directory.iterdir()):
            if path.suffix in (".log", ".csv"):
                compressed = compress_retained_file(path, remove_original=True)
                report["raw_files"].append(str(compressed))
                if path.name == "probe.csv":
                    report["probe_result"]["raw_path"] = str(compressed)
                    report["probe_result"]["accounting"]["source_path"] = str(compressed)
    _atomic_write_json(directory / "capability.json", report)
    return report
