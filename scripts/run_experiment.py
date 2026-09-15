#!/usr/bin/env python3
"""Launch, inspect, gracefully stop or resume a frozen SUCHAI experiment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Use the very same interpreter without user-site shadowing, before importing
# project dependencies. This creates no environment and changes no installation.
if __name__ == "__main__" and not sys.flags.no_user_site:
    os.execv(sys.executable, [sys.executable, "-s", *sys.argv])
sys.path.insert(0, str(ROOT / "src"))
MASTER_STARTED = {"captured_utc": datetime.now(timezone.utc).isoformat(),
                  "monotonic_seconds": time.monotonic(), "process_cpu_seconds": time.process_time()}

from pcsuchai.experiment import ExperimentManifest
from pcsuchai.experiment_control import experiment_status, process_identity, request_experiment_stop
from pcsuchai.experiment_runner import run_experiment, safe_name
from pcsuchai.run_lock import DeviceBusyError, device_run_lock, inherited_lock_fds
from pcsuchai.operation_costs import OperationCosts


def _directory(output_root: Path, label: str, name: str) -> Path:
    """Reserve a sortable UTC identity; no existing experiment is overwritten."""

    now = datetime.now(timezone.utc)
    return (output_root / safe_name(label) / now.strftime("%Y/%m/%d") /
            f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{safe_name(name)}").resolve()


def _detached(command: list[str], directory: Path, environment: dict[str, str]) -> dict:
    """Detach with closed terminal streams and retain the verified launch handle.

    The device lock is passed to the child; the parent never removes its inode.
    Readiness requires that exact child's durable segment identity. Observation
    timeout returns its real live handle, never starts a second experiment.
    """

    from pcsuchai.benchmark_suite import _atomic_write_json, _utc_path_stamp
    launch_id = _utc_path_stamp()
    log_path = directory / f"launch-{launch_id}.log"
    with log_path.open("xb") as log, open(os.devnull, "rb") as input_stream:
        child = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=input_stream,
                                 stdout=log, stderr=log, start_new_session=True,
                                 pass_fds=inherited_lock_fds(environment))
    record = {"pid": child.pid, "identity": process_identity(child.pid), "command": command,
              "log_path": str(log_path), "directory": str(directory), "launch_id": launch_id}
    _atomic_write_json(directory / f"launch-{launch_id}.json", record)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state_path = directory / "experiment-state.json"
        if state_path.is_file():
            status = experiment_status(directory)
            if status.get("identity", {}).get("pid") == child.pid:
                return {**record, "ready": True, "state": status}
        code = child.poll()
        if code is not None:
            return {**record, "ready": False, "return_code": code, "reason": "child exited before readiness; inspect launch log"}
        time.sleep(0.1)
    return {**record, "ready": False, "live": child.poll() is None, "return_code": child.poll(),
            "reason": "readiness observation expired; do not relaunch while this handle is live"}


def main() -> int:
    """Expose the same controls for fixed work, timed and persistent experiments."""

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--device-label", required=True)
    run.add_argument("--output-root", type=Path, default=ROOT / "outputs/benchmarks")
    run.add_argument("--session-dir", type=Path, default=None, help=argparse.SUPPRESS)
    run.add_argument("--prepared", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--detach", action="store_true")
    resume = commands.add_parser("resume")
    resume.add_argument("directory", type=Path)
    resume.add_argument("--detach", action="store_true")
    for name in ("status", "stop"):
        sub = commands.add_parser(name)
        sub.add_argument("directory", type=Path)
    export = commands.add_parser("export", help="retain all original bytes in a verified transfer bundle")
    export.add_argument("directory", type=Path)
    export.add_argument("--output", type=Path, required=True)
    imported = commands.add_parser("import", help="verify a bundle into a new directory without overwriting")
    imported.add_argument("bundle", type=Path)
    imported.add_argument("directory", type=Path)
    imported.add_argument("--sha256", default=None)
    verify = commands.add_parser("verify-import", help="audit every original imported file")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--images", action="store_true", help="also decode saved images and check their retained scientific masks")
    report = commands.add_parser("report", help="reconstruct attempts, uncertainty and numerical checks from saved experiments")
    report.add_argument("directories", type=Path, nargs="+")
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--seed", type=int, default=1729)
    report.add_argument("--resamples", type=int, default=2000)
    report.add_argument("--storage-planned-attempts", type=int,
                        help="additional started jobs per exact cohort, including warmups/failures")
    report.add_argument("--storage-reserve-bytes", type=int,
                        help="explicit headroom for temporary files, commit, setup and finalization; never inferred from final output size")
    report.add_argument("--thermal-window-seconds", type=float, default=300)
    report.add_argument("--thermal-maximum-slope-c-per-minute", type=float, default=0.2)
    report.add_argument("--thermal-maximum-range-c", type=float, default=2)
    report.add_argument("--thermal-maximum-gap-factor", type=float, default=1.5)
    report.add_argument("--thermal-consecutive-windows", type=int, default=2)
    costs = commands.add_parser("costs", help="audit saved whole-operation receipts without rerunning science")
    costs.add_argument("directories", type=Path, nargs="+")
    costs.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    master_costs = None
    master_result = None
    master_error = None
    try:
        if arguments.command == "costs":
            from pcsuchai.operation_costs import report_operation_costs
            result = report_operation_costs(arguments.directories, arguments.output)
            print(json.dumps(result, indent=2))
            return 2 if result["status"] == "incomplete_or_invalid" else 0
        if arguments.command == "report":
            from pcsuchai.experiment_report import report_experiments
            from pcsuchai.thermal_analysis import ThermalAnalysisPolicy
            thermal = ThermalAnalysisPolicy(arguments.thermal_window_seconds, arguments.thermal_maximum_slope_c_per_minute,
                                            arguments.thermal_maximum_range_c, arguments.thermal_maximum_gap_factor,
                                            arguments.thermal_consecutive_windows)
            result = report_experiments(arguments.directories, arguments.output, seed=arguments.seed,
                                        resamples=arguments.resamples, thermal_policy=thermal,
                                        storage_planned_attempts=arguments.storage_planned_attempts,
                                        storage_reserve_bytes=arguments.storage_reserve_bytes)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "diagnostic_report_created" else 2
        if arguments.command in ("export", "import", "verify-import"):
            from pcsuchai.portable import export_experiment, import_experiment, verify_import
            if arguments.command == "export":
                result = export_experiment(arguments.directory, arguments.output)
            elif arguments.command == "import":
                result = import_experiment(arguments.bundle, arguments.directory, expected_sha256=arguments.sha256)
            else:
                result = verify_import(arguments.directory, verify_images=arguments.images)
            print(json.dumps(result, indent=2))
            return 2 if result.get("passed") is False else 0
        if arguments.command in ("status", "stop"):
            result = experiment_status(arguments.directory) if arguments.command == "status" else request_experiment_stop(arguments.directory)
            print(json.dumps(result, indent=2))
            return 0
        with device_run_lock():
            resuming = arguments.command == "resume"
            if resuming:
                directory = arguments.directory.resolve()
                manifest = ExperimentManifest.load(directory / "manifest.json")
                state = json.loads((directory / "experiment-state.json").read_text())
                label = state["device_label"]
            else:
                manifest = ExperimentManifest.load(arguments.manifest)
                label = arguments.device_label
                directory = arguments.session_dir.resolve() if arguments.session_dir else _directory(arguments.output_root, label, manifest.data["name"])
            print(f"EXPERIMENT: {directory}", flush=True)
            master_costs = OperationCosts(directory.parent / "operation-costs", "master-" + arguments.command,
                scope="master_post_stdlib_bootstrap_to_return",
                context={"experiment_directory": str(directory), "manifest_sha256": manifest.sha256,
                         "device_label": label, "detached_launcher": arguments.detach,
                         "limit": "starts before project imports in this post-reexec process; excludes interpreter/stdlib/-s reexec startup and own terminal write; contains API work, not an additive job cost"},
                started=MASTER_STARTED)
            print(f"MASTER_COST_RECEIPT: {master_costs.directory}", file=sys.stderr, flush=True)
            if arguments.detach:
                if not resuming:
                    from pcsuchai.benchmark_suite import _atomic_write_json
                    directory.mkdir(parents=True, exist_ok=False)
                    _atomic_write_json(directory / "manifest.json", manifest.data)
                    command = [sys.executable, str(Path(__file__).resolve()), "run", "--manifest", str(directory / "manifest.json"),
                               "--device-label", label, "--session-dir", str(directory), "--prepared"]
                else:
                    command = [sys.executable, str(Path(__file__).resolve()), "resume", str(directory)]
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(ROOT / "src")
                environment["PYTHONNOUSERSITE"] = "1"
                if environment.get("PCSUCHAI_LAUNCH_OBSERVATION") is not None:
                    environment["PCSUCHAI_LAUNCH_OBSERVATION"] = json.dumps({
                        "attachment_scope": "upstream_detached_launcher_only_not_active_job_tee",
                        "upstream_declaration": environment["PCSUCHAI_LAUNCH_OBSERVATION"]}, sort_keys=True)
                result = _detached(command, directory, environment)
                master_result = {"status": "detached_handoff", "launch": result}
                print(json.dumps(result, indent=2))
                return 2 if result.get("return_code") not in (None, 0) else 0
            result = run_experiment(manifest, directory, ROOT, label, resume=resuming,
                                    prepared=arguments.prepared if not resuming else False)
            master_result = result
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "complete" else 2
    except (DeviceBusyError, ValueError, OSError, KeyError) as exc:
        master_error = {"type": type(exc).__name__, "message": str(exc)}
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except BaseException as exc:
        master_error = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if master_costs is not None:
            master_costs.finish(status="raised" if master_error else "returned", error=master_error,
                                outcome=master_result.get("status") if master_result else None,
                                extra={"returned_result": master_result})


if __name__ == "__main__":
    raise SystemExit(main())
