#!/usr/bin/env python3
"""Run one declared PCS SUCHAI benchmark campaign without hand-built commands."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from pcsuchai.run_lock import DeviceBusyError, device_run_lock, inherited_lock_fds


def _safe_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    if not cleaned:
        raise ValueError("device label must contain at least one letter or number")
    return cleaned


def _run(command: list[str], *, cwd: Path, env: dict[str, str], log_path: Path) -> None:
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            pass_fds=inherited_lock_fds(env),
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
        return_code = process.wait()
    if return_code:
        raise SystemExit(f"command failed with exit code {return_code}; see {log_path}")


def _campaign_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--device-label", default=None, help="non-identifying label such as pi5-active-cooler")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/benchmarks"))
    stopping = parser.add_mutually_exclusive_group()
    stopping.add_argument("--duration-hours", type=float, default=None, help="override the profile with a measured deadline")
    stopping.add_argument("--attempts-per-pair", type=int, default=None, help="override the profile with exactly this many scheduled attempts per pair")
    parser.add_argument("--session-index", type=int, default=None, help="one-based independent-session index for balanced ordering")
    parser.add_argument("--resume-session", type=Path, default=None, help="resume an existing dated session directory")
    parser.add_argument("--allow-version-drift", action="store_true", help="local development only; never use for cross-Pi results")
    arguments = parser.parse_args()
    if arguments.attempts_per_pair is not None and arguments.attempts_per_pair < 1:
        parser.error("--attempts-per-pair must be positive")
    if arguments.duration_hours is not None and arguments.duration_hours <= 0:
        parser.error("--duration-hours must be positive")
    if arguments.session_index is not None and arguments.session_index < 1:
        parser.error("--session-index must be positive")
    if arguments.resume_session is not None and any(item is not None for item in (arguments.duration_hours, arguments.attempts_per_pair, arguments.session_index)):
        parser.error("resume uses the saved stopping rule and session index; overrides are not allowed")

    root = Path(__file__).resolve().parent.parent
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if arguments.resume_session is not None:
        session_dir = arguments.resume_session.resolve()
        if not session_dir.is_dir():
            raise SystemExit(f"resume session does not exist: {session_dir}")
        config = json.loads((session_dir / "campaign-config.json").read_text(encoding="utf-8"))
        checkpoint = json.loads(
            (session_dir / "benchmark" / "benchmark-session.checkpoint.json").read_text(encoding="utf-8")
        )
        label = _safe_label(checkpoint["device_label"])
        # Older launchers saved the original profile, not effective overrides.
        if checkpoint.get("settings", {}).get("duration_seconds") is not None:
            config["duration_hours"] = checkpoint["settings"]["duration_seconds"] / 3600.0
        if arguments.notes is None:
            arguments.notes = checkpoint.get("notes")
        if arguments.device_label is not None and _safe_label(arguments.device_label) != label:
            raise SystemExit("resume device label does not match the checkpoint")
    else:
        if arguments.config is None or arguments.device_label is None:
            parser.error("--config and --device-label are required for a new campaign")
        config_path = (root / arguments.config).resolve() if not arguments.config.is_absolute() else arguments.config
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if arguments.duration_hours is not None:
            config["duration_hours"] = arguments.duration_hours
            config["repeats"] = None
        if arguments.attempts_per_pair is not None:
            config["repeats"] = arguments.attempts_per_pair
            config.pop("duration_hours", None)
        if arguments.session_index is not None:
            config["session_index"] = arguments.session_index
        label = _safe_label(arguments.device_label)
        now = datetime.now(timezone.utc)
        session_dir = (
            root / arguments.output_root / label / now.strftime("%Y") / now.strftime("%m")
            / now.strftime("%d") / f"{stamp}-{_safe_label(config['name'])}"
        ).resolve()
        session_dir.mkdir(parents=True, exist_ok=False)
        (session_dir / "campaign-config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    print(f"SESSION: {session_dir}", flush=True)
    env = os.environ.copy()
    # Global Pi installation must not be shadowed by leftovers from the former
    # --user installer. This is a Python startup option, not an environment.
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    python = sys.executable
    orbit = [str(item) for item in config["orbit_backends"]]
    magnetic = [str(item) for item in config["magnetic_backends"]]

    preflight = [
        python, "-m", "pcsuchai", "preflight", "--project-root", str(root),
        "--output-dir", str(session_dir / "write-probe"),
        "--report", str(session_dir / "preflight.json"),
        "--orbit-backends", *orbit, "--magnetic-backends", *magnetic,
    ]
    if not arguments.allow_version_drift:
        preflight.extend(("--version-policy", str(root / "requirements/rpi-version-policy.txt")))
        if config.get("python_version"):
            preflight.extend(("--expected-python", str(config["python_version"])))
    log_suffix = f"-{stamp}" if arguments.resume_session is not None else ""
    preflight_report = session_dir / f"preflight{log_suffix}.json"
    preflight[preflight.index(str(session_dir / "preflight.json"))] = str(preflight_report)
    _run(preflight, cwd=root, env=env, log_path=session_dir / f"preflight{log_suffix}.log")

    snapshot = session_dir / f"hardware-and-os{log_suffix}.txt"
    with snapshot.open("w", encoding="utf-8") as handle:
        result = subprocess.run(["bash", "scripts/collect_system_info.sh"], cwd=root, env=env, text=True, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f"hardware snapshot failed; see {snapshot}")

    validation_certificate = None
    if config.get("official"):
        if not config.get("plot_config"):
            raise SystemExit("official campaign configuration requires plot_config")
        validation_dir = session_dir / "full-validation"
        if arguments.resume_session is None:
            validation_command = [
                python, "-m", "pcsuchai", "validate-full",
                "--project-root", str(root), "--output-dir", str(validation_dir),
                "--plot-config", str(root / config["plot_config"]),
            ]
            if config.get("limit") is not None:
                validation_command.extend(("--limit", str(config["limit"])))
            _run(
                validation_command, cwd=root, env=env,
                log_path=session_dir / "full-validation.log",
            )
        validation_certificate = validation_dir / "full-validation-certificate.json"

    command = [
        python, "-m", "pcsuchai", "benchmark-suite",
        "--project-root", str(root), "--output-dir", str(session_dir / "benchmark"),
        "--device-label", label, "--orbit-backends", *orbit,
        "--magnetic-backends", *magnetic,
        "--warmups", str(config["warmups"]), "--seed", str(config.get("seed", 1729)),
        "--cooldown-seconds", str(config.get("cooldown_seconds", 0)),
        "--cooldown-max-seconds", str(config.get("cooldown_max_seconds", 600)),
        "--timeout-seconds", str(config.get("timeout_seconds", 7200)),
    ]
    duration_hours = arguments.duration_hours if arguments.duration_hours is not None else config.get("duration_hours")
    if duration_hours is not None:
        command.extend(("--duration-seconds", str(float(duration_hours) * 3600.0)))
    elif config.get("repeats") is not None:
        command.extend(("--repeats", str(config["repeats"])))
    if arguments.notes:
        command.extend(("--notes", arguments.notes))
    if config.get("limit") is not None:
        command.extend(("--limit", str(config["limit"])))
    if config.get("plot_config"):
        command.extend(("--plot-config", str(root / config["plot_config"])))
    if config.get("cooldown_until_c") is not None:
        command.extend(("--cooldown-until-c", str(config["cooldown_until_c"])))
    if config.get("collect_perf"):
        command.append("--perf")
    command.extend((
        "--telemetry-interval-seconds", str(config.get("telemetry_interval_seconds", 2.0)),
        "--minimum-free-gb", str(config.get("minimum_free_gb", 1.0)),
        "--max-consecutive-failures", str(config.get("max_consecutive_failures", 3)),
        "--ordering", str(config.get("ordering", "randomized")),
        "--session-index", str(config.get("session_index", 1)),
        "--thread-policy", str(config.get("thread_policy", "stock")),
        "--process-mode", str(config.get("process_mode", "fresh")),
        "--selection-method", str(config.get("selection_method", "prefix")),
    ))
    if config.get("thermal_policy") is not None:
        thermal_path = session_dir / "thermal-policy.json"
        if arguments.resume_session is None:
            thermal_path.write_text(json.dumps(config["thermal_policy"], indent=2) + "\n", encoding="utf-8")
        command.extend(("--thermal-policy", str(thermal_path)))
    if config.get("maximum_temperature_c") is not None:
        command.extend(("--maximum-temperature-c", str(config["maximum_temperature_c"])))
    if config.get("continue_on_error"):
        command.append("--continue-on-error")
    if arguments.resume_session is not None:
        command.append("--resume")
    if config.get("official"):
        command.extend(("--official", "--validation-certificate", str(validation_certificate)))

    (session_dir / f"command{log_suffix}.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    _run(command, cwd=root, env=env, log_path=session_dir / f"campaign{log_suffix}.log")
    print(f"\nCOMPLETE: {session_dir}")
    return 0


def main() -> int:
    """Keep validation, recovery and measured jobs under one device-wide lock."""

    try:
        with device_run_lock():
            return _campaign_main()
    except DeviceBusyError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
