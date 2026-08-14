"""Isolated, repeated benchmark orchestration and statistical summaries."""

from __future__ import annotations

import json
import csv
import random
import shutil
import subprocess
import sys
import time
import hashlib
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev

from .benchmark import _temperature_c, runtime_metadata, sha256_file, system_snapshot


def _utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def _utc_text(moment: datetime | None = None) -> str:
    """Return an ISO-8601 UTC timestamp suitable for machine-readable records."""

    return (moment or _utc_now()).isoformat()


def _utc_path_stamp(moment: datetime | None = None) -> str:
    """Return a sortable, collision-resistant UTC timestamp for directory names."""

    return (moment or _utc_now()).strftime("%Y%m%dT%H%M%S.%fZ")


def _atomic_write_json(path: Path, value: object) -> None:
    """Durably replace a JSON checkpoint without exposing a partial document."""

    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _append_jsonl(path: Path, record: dict) -> None:
    """Append and flush one independent event record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _telemetry_snapshot(storage_path: Path) -> dict:
    """Capture low-overhead host telemetry for the append-only campaign timeline."""

    snapshot = {
        "captured_utc": _utc_text(),
        "temperature_c": _temperature_c(),
        "load_1m": os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
        "disk_free_bytes": shutil.disk_usage(storage_path).free,
    }
    try:
        import psutil

        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        frequency = psutil.cpu_freq()
        snapshot.update({
            "available_memory_bytes": int(memory.available),
            "used_memory_bytes": int(memory.used),
            "swap_used_bytes": int(swap.used),
            "cpu_frequency_mhz": float(frequency.current) if frequency else None,
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
        })
    except (ImportError, OSError):
        snapshot.update({
            "available_memory_bytes": None, "used_memory_bytes": None,
            "swap_used_bytes": None, "cpu_frequency_mhz": None, "cpu_percent": None,
        })
    return snapshot


class _TelemetryJournal:
    """Continuously append timestamped system samples without retaining them in RAM."""

    fields = (
        "captured_utc", "campaign_elapsed_seconds", "run_id", "run_directory", "scenario", "phase",
        "temperature_c", "cpu_frequency_mhz", "cpu_percent", "available_memory_bytes",
        "used_memory_bytes", "swap_used_bytes", "load_1m", "disk_free_bytes",
    )

    def __init__(self, path: Path, storage_path: Path, interval_seconds: float) -> None:
        self.path = path
        self.storage_path = storage_path
        self.interval_seconds = interval_seconds
        self.started = time.monotonic()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.context = {"run_id": None, "run_directory": None, "scenario": None, "phase": "idle"}
        self.thread: threading.Thread | None = None

    def set_context(
        self, *, run_id: str | None, run_directory: Path | None = None,
        scenario: str | None, phase: str,
    ) -> None:
        """Label future samples with the active workload."""

        with self.lock:
            self.context = {
                "run_id": run_id, "run_directory": str(run_directory) if run_directory else None,
                "scenario": scenario, "phase": phase,
            }

    def sample(self) -> dict:
        """Append one sample immediately and return it for safety checks."""

        record = _telemetry_snapshot(self.storage_path)
        with self.lock:
            record.update(self.context)
        record["campaign_elapsed_seconds"] = time.monotonic() - self.started
        def append(path: Path) -> None:
            exists = path.exists() and path.stat().st_size > 0
            with path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=self.fields)
                if not exists:
                    writer.writeheader()
                writer.writerow({name: record.get(name) for name in self.fields})
                handle.flush()
                os.fsync(handle.fileno())
        with self.write_lock:
            append(self.path)
            if record.get("run_directory"):
                append(Path(str(record["run_directory"])) / "system-telemetry.csv")
            _atomic_write_json(self.path.parent / "heartbeat.json", record)
        return record

    def start(self) -> None:
        """Start the background sampler after recording an immediate baseline."""

        self.sample()

        def loop() -> None:
            while not self.stop_event.wait(self.interval_seconds):
                self.sample()

        self.thread = threading.Thread(target=loop, name="pcsuchai-telemetry", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the sampler and append one final sample."""

        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=max(1.0, self.interval_seconds * 2))
        self.sample()


@dataclass(frozen=True)
class BenchmarkScenario:
    """One orbit/magnetic implementation combination."""

    orbit_backend: str
    magnetic_backend: str

    @property
    def name(self) -> str:
        """Return a filename-safe scenario identifier."""

        return f"{self.orbit_backend}-{self.magnetic_backend}"


def _statistics(values: list[float]) -> dict[str, float]:
    """Summarize repeated numeric measurements deterministically."""

    ordered = sorted(values)
    position = 0.95 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    p95 = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {
        "mean": mean(values), "median": median(values),
        "standard_deviation": pstdev(values), "minimum": min(values),
        "maximum": max(values), "p95": p95,
    }


def _artifact_record(path: str | Path) -> dict[str, str | int]:
    """Record the size and digest of one benchmark artifact."""

    artifact = Path(path)
    return {
        "path": str(artifact), "size_bytes": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
    }


def _source_digest(project_root: Path) -> dict[str, object]:
    """Identify executable project sources without relying on Git metadata."""

    source_suffixes = {".py", ".sh", ".json", ".txt", ".patch", ".npz", ".md"}
    files = sorted({
        path for base in ("src", "scripts", "configs", "requirements", "packaging")
        for path in (project_root / base).rglob("*")
        if path.is_file() and path.suffix in source_suffixes and "__pycache__" not in path.parts
    } | {project_root / "pyproject.toml"})
    digest = hashlib.sha256()
    records = []
    for path in files:
        relative = path.relative_to(project_root).as_posix()
        file_hash = sha256_file(path)
        digest.update(relative.encode("utf-8") + b"\0" + file_hash.encode("ascii") + b"\n")
        records.append({"path": relative, "sha256": file_hash, "size_bytes": path.stat().st_size})
    return {"sha256": digest.hexdigest(), "file_count": len(records), "files": records}


def _cooldown(target_c: float | None, fixed_seconds: float, max_seconds: float) -> dict:
    """Apply an optional fixed delay and/or wait for a thermal baseline."""

    started = time.monotonic()
    samples = []
    if fixed_seconds:
        time.sleep(fixed_seconds)
    status = "fixed_delay_complete"
    if target_c is not None:
        while True:
            temperature = _temperature_c()
            samples.append({"elapsed_seconds": time.monotonic() - started, "temperature_c": temperature})
            if temperature is None:
                status = "temperature_sensor_unavailable"
                break
            if temperature <= target_c:
                status = "target_reached"
                break
            if time.monotonic() - started >= max_seconds:
                status = "maximum_wait_reached"
                break
            time.sleep(min(5.0, max(0.1, max_seconds - (time.monotonic() - started))))
    return {
        "status": status, "target_c": target_c, "fixed_seconds": fixed_seconds,
        "max_seconds": max_seconds, "elapsed_seconds": time.monotonic() - started,
        "samples": samples,
    }


def parse_perf_stat(path: str | Path) -> dict[str, float | str | None]:
    """Parse semicolon-separated ``perf stat`` output without assuming support."""

    result: dict[str, float | str | None] = {}
    for line in Path(path).read_text(errors="replace").splitlines():
        parts = [item.strip() for item in line.split(";")]
        if len(parts) < 3 or not parts[2]:
            continue
        raw, event = parts[0].replace(",", ""), parts[2]
        try:
            result[event] = float(raw)
        except ValueError:
            result[event] = None if raw.startswith("<not") else raw
    return result


def _analysis_command(
    scenario: BenchmarkScenario,
    output_dir: Path,
    measurements: Path,
    tle: Path,
    eop: Path,
    plot_config: Path | None,
    limit: int | None,
    benchmark: bool = True,
) -> list[str]:
    """Build the exact child command used for every isolated run."""

    command = [
        sys.executable, "-m", "pcsuchai", "analyze",
        "--measurements", str(measurements), "--tle", str(tle),
        "--eop", str(eop), "--output-dir", str(output_dir),
        "--orbit-backend", scenario.orbit_backend,
        "--magnetic-backend", scenario.magnetic_backend,
    ]
    if benchmark:
        command.append("--benchmark")
    if plot_config is not None:
        command.extend(("--plot-config", str(plot_config)))
    if limit is not None:
        command.extend(("--limit", str(limit)))
    return command


def _run_child(
    command: list[str], timeout_seconds: float, environment: dict[str, str] | None = None
) -> tuple[dict, float, str]:
    """Run one clean process and parse its JSON result."""

    started = time.perf_counter()
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout_seconds, check=False,
        env=environment,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(
            f"benchmark child failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-4000:]}"
        )
    try:
        outputs = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"benchmark child returned invalid JSON: {result.stdout[-4000:]}") from exc
    return outputs, elapsed, result.stderr


def _validate_run(outputs: dict, external_wall_seconds: float) -> dict:
    """Validate required products and collect their hashes and stage records."""

    required = (
        "positions_csv", "particle_map_png", "manifest_json", "benchmark_json",
        "magnetic_positions_csv", "magnetic_particle_map_png", "footpoint_particle_map_png",
    )
    missing = [name for name in required if not outputs.get(name) or not Path(outputs[name]).is_file()]
    if missing:
        raise RuntimeError(f"benchmark run is missing artifacts: {', '.join(missing)}")
    manifest = json.loads(Path(outputs["manifest_json"]).read_text())
    if manifest["valid_positions"] <= 0 or manifest["observations"] <= 0:
        raise RuntimeError("benchmark run produced no valid orbit observations")
    stages = json.loads(Path(outputs["benchmark_json"]).read_text())
    artifacts = {name: _artifact_record(outputs[name]) for name in required}
    configured = [_artifact_record(path) for path in outputs.get("configured_plot_files", [])]
    return {
        "external_wall_seconds": external_wall_seconds,
        "observations": manifest["observations"],
        "valid_positions": manifest["valid_positions"],
        "valid_magnetic_positions": manifest["valid_magnetic_positions"],
        "artifacts": artifacts,
        "configured_plot_artifacts": configured,
        "output_bytes": sum(item["size_bytes"] for item in artifacts.values())
        + sum(item["size_bytes"] for item in configured),
        "stages": stages,
    }


def _summarize_runs(runs: list[dict]) -> dict:
    """Aggregate whole-process and per-stage measurements across repeats."""

    stage_names = sorted({stage["stage"] for run in runs for stage in run["stages"]})
    stage_fields = (
        "wall_seconds", "process_cpu_seconds", "process_user_seconds",
        "process_system_seconds", "peak_rss_bytes", "read_bytes", "write_bytes",
        "read_chars", "write_chars", "rss_change_bytes", "cpu_equivalent_percent",
        "voluntary_context_switches", "involuntary_context_switches",
        "minor_page_faults", "major_page_faults", "peak_threads",
        "available_memory_start_bytes", "available_memory_min_bytes",
        "available_memory_end_bytes", "temperature_start_c", "temperature_max_c",
        "temperature_end_c", "cpu_frequency_min_mhz", "cpu_frequency_max_mhz",
    )
    stage_summary = {}
    for stage_name in stage_names:
        rows = [
            next(stage for stage in run["stages"] if stage["stage"] == stage_name)
            for run in runs
        ]
        stage_summary[stage_name] = {
            field: _statistics([float(row[field]) for row in rows if row[field] is not None])
            for field in stage_fields
            if any(row[field] is not None for row in rows)
        }
    return {
        "external_wall_seconds": _statistics([run["external_wall_seconds"] for run in runs]),
        "output_bytes": _statistics([float(run["output_bytes"]) for run in runs]),
        "stages": stage_summary,
    }


def _check_repeat_consistency(runs: list[dict]) -> dict:
    """Require deterministic scientific tables across identical repeats."""

    roles = ("positions_csv", "magnetic_positions_csv")
    result = {}
    for role in roles:
        hashes = [run["artifacts"][role]["sha256"] for run in runs]
        result[role] = {"consistent": len(set(hashes)) == 1, "sha256": hashes}
    result["all_consistent"] = all(item["consistent"] for item in result.values())
    return result


def _write_csv_reports(session: dict, destination: Path) -> dict[str, str]:
    """Write operator-friendly summaries without discarding the complete JSON."""

    run_path = destination / "run-timeseries.csv"
    with run_path.open("w", encoding="utf-8", newline="") as handle:
        columns = [
            "run_id", "started_utc", "finished_utc", "run_directory",
            "scenario", "repeat", "external_wall_seconds", "output_bytes",
            "temperature_before_c", "temperature_after_c", "memory_available_before_bytes",
            "memory_available_after_bytes", "cpu_frequency_before_mhz",
            "cpu_frequency_after_mhz", "throttled_before", "throttled_after",
            "valid_positions", "valid_magnetic_positions",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for scenario, report in session["scenarios"].items():
            for run in report["runs"]:
                before, after = run["system_before"], run["system_after"]
                writer.writerow({
                    "run_id": run.get("run_id"),
                    "started_utc": run.get("started_utc"),
                    "finished_utc": run.get("finished_utc"),
                    "run_directory": run.get("run_directory"),
                    "scenario": scenario, "repeat": run["repeat"],
                    "external_wall_seconds": run["external_wall_seconds"],
                    "output_bytes": run["output_bytes"],
                    "temperature_before_c": before.get("temperature_c"),
                    "temperature_after_c": after.get("temperature_c"),
                    "memory_available_before_bytes": before.get("available_memory_bytes"),
                    "memory_available_after_bytes": after.get("available_memory_bytes"),
                    "cpu_frequency_before_mhz": before.get("cpu_frequency_mhz"),
                    "cpu_frequency_after_mhz": after.get("cpu_frequency_mhz"),
                    "throttled_before": before.get("throttled"),
                    "throttled_after": after.get("throttled"),
                    "valid_positions": run["valid_positions"],
                    "valid_magnetic_positions": run["valid_magnetic_positions"],
                })

    stage_path = destination / "stage-timeseries.csv"
    stage_fields = (
        "wall_seconds", "process_cpu_seconds", "process_user_seconds",
        "process_system_seconds", "cpu_equivalent_percent", "peak_rss_bytes",
        "rss_change_bytes", "read_bytes", "write_bytes", "read_chars", "write_chars",
        "voluntary_context_switches", "involuntary_context_switches",
        "minor_page_faults", "major_page_faults", "peak_threads",
        "available_memory_start_bytes", "available_memory_min_bytes",
        "available_memory_end_bytes", "temperature_start_c", "temperature_max_c",
        "temperature_end_c", "cpu_frequency_min_mhz", "cpu_frequency_max_mhz",
        "throttled_start", "throttled_end",
    )
    with stage_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "run_id", "scenario", "repeat", "stage", "started_utc", "finished_utc",
            *stage_fields,
        ))
        writer.writeheader()
        for scenario, report in session["scenarios"].items():
            for run in report["runs"]:
                for stage in run["stages"]:
                    writer.writerow({
                        "run_id": run.get("run_id"),
                        "scenario": scenario, "repeat": run["repeat"],
                        "stage": stage["stage"],
                        "started_utc": stage.get("started_utc"),
                        "finished_utc": stage.get("finished_utc"),
                        **{field: stage.get(field) for field in stage_fields},
                    })

    summary_path = destination / "scenario-summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        columns = ["scenario", "stage", "metric", "mean", "median", "standard_deviation", "minimum", "maximum", "p95"]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for scenario, report in session["scenarios"].items():
            if "summary" not in report:
                continue
            for stage, metrics in report["summary"]["stages"].items():
                for metric, values in metrics.items():
                    writer.writerow({"scenario": scenario, "stage": stage, "metric": metric, **values})
            writer.writerow({
                "scenario": scenario, "stage": "WHOLE_PROCESS",
                "metric": "external_wall_seconds",
                **report["summary"]["external_wall_seconds"],
            })
    return {
        "run_timeseries_csv": str(run_path),
        "stage_timeseries_csv": str(stage_path),
        "scenario_summary_csv": str(summary_path),
    }


def _perf_run(
    command: list[str], perf_path: Path, timeout_seconds: float,
    environment: dict[str, str] | None = None,
) -> dict:
    """Optionally perform a separate hardware-counter run via Linux perf."""

    executable = shutil.which("perf")
    if executable is None:
        return {"status": "unavailable", "reason": "perf executable not installed"}
    perf_command = [
        executable, "stat", "-x", ";", "-o", str(perf_path), "-e",
        "cycles,instructions,task-clock,context-switches,page-faults", "--", *command,
    ]
    result = subprocess.run(
        perf_command, capture_output=True, text=True, timeout=timeout_seconds,
        check=False, env=environment,
    )
    if result.returncode != 0:
        return {
            "status": "unavailable", "reason": result.stderr[-2000:],
            "return_code": result.returncode,
        }
    return {"status": "available", "counters": parse_perf_stat(perf_path)}


def run_benchmark_suite(
    output_dir: str | Path,
    measurements: str | Path,
    tle: str | Path,
    eop: str | Path,
    orbit_backends: tuple[str, ...] = ("astropy", "skyfield"),
    magnetic_backends: tuple[str, ...] = ("aacgmv2", "apexpy"),
    plot_config: str | Path | None = None,
    repeats: int | None = 3,
    warmups: int = 1,
    seed: int = 1729,
    limit: int | None = None,
    cooldown_seconds: float = 0.0,
    timeout_seconds: float = 3600.0,
    collect_perf: bool = False,
    cooldown_until_c: float | None = None,
    cooldown_max_seconds: float = 600.0,
    device_label: str | None = None,
    notes: str | None = None,
    project_root: str | Path = ".",
    official: bool = False,
    validation_certificate: str | Path | None = None,
    duration_seconds: float | None = None,
    telemetry_interval_seconds: float = 2.0,
    minimum_free_bytes: int = 1_000_000_000,
    maximum_temperature_c: float | None = None,
    continue_on_error: bool = False,
    max_consecutive_failures: int = 3,
    resume: bool = False,
) -> dict:
    """Run a durable finite or duration-based clean-process benchmark campaign."""

    if duration_seconds is None and (repeats is None or repeats < 2):
        raise ValueError("benchmark suite requires at least two repeats or a duration")
    if repeats is not None and repeats < 2:
        raise ValueError("repeats must be at least two when specified")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if telemetry_interval_seconds <= 0 or minimum_free_bytes < 0 or max_consecutive_failures < 1:
        raise ValueError("telemetry interval/failure limit must be positive and free space nonnegative")
    if warmups < 0 or cooldown_seconds < 0 or cooldown_max_seconds < 0 or timeout_seconds <= 0:
        raise ValueError("warmups/cooldown must be nonnegative and timeout positive")
    destination = Path(output_dir)
    if resume:
        if not destination.is_dir():
            raise ValueError(f"cannot resume missing benchmark directory: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    measurements_path, tle_path, eop_path = map(Path, (measurements, tle, eop))
    plot_path = Path(plot_config) if plot_config is not None else None
    resolved_root = Path(project_root).resolve()
    child_environment = os.environ.copy()
    child_environment["PYTHONPATH"] = str(resolved_root / "src") + (
        os.pathsep + child_environment["PYTHONPATH"] if child_environment.get("PYTHONPATH") else ""
    )
    inputs = {"measurements": measurements_path, "tle": tle_path, "eop": eop_path}
    if plot_path is not None:
        inputs["plot_config"] = plot_path
    for name, path in inputs.items():
        if not path.is_file():
            raise ValueError(f"missing benchmark input {name}: {path}")
    certificate_verification = None
    if official:
        if tuple(orbit_backends) != ("astropy", "skyfield") or tuple(magnetic_backends) != ("aacgmv2", "apexpy"):
            raise ValueError(
                "official benchmark requires the complete Astropy/Skyfield × AACGMv2/ApexPy matrix"
            )
        if plot_path is None:
            raise ValueError("official full-code benchmarks require a plot configuration")
        if validation_certificate is None:
            raise ValueError("official benchmark requires a full-code validation certificate")
        from .full_validation import verify_validation_certificate

        certificate_verification = verify_validation_certificate(
            validation_certificate, project_root, measurements_path, tle_path,
            eop_path, plot_path, limit,
        )
        if not certificate_verification["passed"]:
            failed = [name for name, passed in certificate_verification["checks"].items() if not passed]
            raise ValueError(f"validation certificate does not match this workload: {', '.join(failed)}")

    scenarios = tuple(
        BenchmarkScenario(orbit, magnetic)
        for orbit in orbit_backends for magnetic in magnetic_backends
    )
    current_source = _source_digest(resolved_root)
    current_runtime = runtime_metadata()
    current_inputs = {
        name: {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for name, path in inputs.items()
    }
    current_settings = {
        "repeats": repeats, "warmups": warmups, "seed": seed, "limit": limit,
        "duration_seconds": duration_seconds,
        "cooldown_seconds": cooldown_seconds, "timeout_seconds": timeout_seconds,
        "collect_perf": collect_perf, "cooldown_until_c": cooldown_until_c,
        "cooldown_max_seconds": cooldown_max_seconds,
        "telemetry_interval_seconds": telemetry_interval_seconds,
        "minimum_free_bytes": minimum_free_bytes,
        "maximum_temperature_c": maximum_temperature_c,
        "continue_on_error": continue_on_error,
        "max_consecutive_failures": max_consecutive_failures,
        "artifact_retention": "all",
    }
    new_session = {
        "schema_version": 2,
        "status": "running",
        "official": official,
        "workload_classification": "validated_full_code" if official else "diagnostic_non_official",
        "validation_certificate": certificate_verification,
        "started_utc": _utc_text(),
        "device_label": device_label,
        "notes": notes,
        "runtime": current_runtime,
        "source": current_source,
        "system_start": system_snapshot(),
        "settings": current_settings,
        "inputs": current_inputs,
        "execution_order": [],
        "failures": [],
        "resume_events": [],
        "active_elapsed_seconds": 0.0,
        "scenarios": {
            scenario.name: {
                "orbit_backend": scenario.orbit_backend,
                "magnetic_backend": scenario.magnetic_backend,
                "runs": [],
            }
            for scenario in scenarios
        },
    }
    checkpoint_path = destination / "benchmark-session.checkpoint.json"
    event_path = destination / "campaign-events.jsonl"
    telemetry_path = destination / "system-telemetry.csv"

    if resume:
        if not checkpoint_path.is_file():
            raise ValueError(f"resume checkpoint is missing: {checkpoint_path}")
        session = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if session.get("status") == "complete":
            raise ValueError("completed benchmark sessions cannot be resumed")
        checks = {
            "source": session.get("source", {}).get("sha256") == current_source["sha256"],
            "python": session.get("runtime", {}).get("python_version") == current_runtime["python_version"],
            "packages": session.get("runtime", {}).get("packages") == current_runtime["packages"],
            "settings": session.get("settings") == current_settings,
            "inputs": {
                name: (record.get("sha256"), record.get("size_bytes"))
                for name, record in session.get("inputs", {}).items()
            } == {
                name: (record["sha256"], record["size_bytes"])
                for name, record in current_inputs.items()
            },
            "scenarios": sorted(session.get("scenarios", {}))
            == sorted(scenario.name for scenario in scenarios),
        }
        if not all(checks.values()):
            failed = ", ".join(name for name, passed in checks.items() if not passed)
            raise ValueError(f"resume workload does not match checkpoint: {failed}")
        resumed = {"resumed_utc": _utc_text(), "checks": checks}
        session.setdefault("resume_events", []).append(resumed)
        session["status"] = "running"
    else:
        session = new_session

    def checkpoint() -> None:
        _atomic_write_json(checkpoint_path, session)

    def log_event(event_type: str, **values: object) -> None:
        _append_jsonl(
            event_path, {"recorded_utc": _utc_text(), "event": event_type, **values}
        )

    def ordered(kind: str, round_number: int) -> list[BenchmarkScenario]:
        order = list(scenarios)
        material = f"{seed}:{kind}:{round_number}".encode("utf-8")
        local_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        random.Random(local_seed).shuffle(order)
        return order

    def dated_run_directory(kind: str, round_number: int, scenario: BenchmarkScenario) -> tuple[str, Path]:
        now = _utc_now()
        run_id = f"{_utc_path_stamp(now)}-r{round_number:06d}-{scenario.name}"
        path = destination / kind / now.strftime("%Y-%m-%d") / run_id
        path.mkdir(parents=True, exist_ok=False)
        return run_id, path

    def already_handled(kind: str, round_number: int, scenario: BenchmarkScenario) -> bool:
        return any(
            item.get("kind") == kind and item.get("round") == round_number
            and item.get("scenario") == scenario.name
            and item.get("status") in ("complete", "failed")
            for item in session["execution_order"]
        )

    def safety_reason(sample: dict) -> str | None:
        if sample["disk_free_bytes"] < minimum_free_bytes:
            return f"disk free space {sample['disk_free_bytes']} below limit {minimum_free_bytes}"
        temperature = sample.get("temperature_c")
        if maximum_temperature_c is not None and temperature is not None and temperature >= maximum_temperature_c:
            return f"temperature {temperature} C reached limit {maximum_temperature_c} C"
        return None

    checkpoint()
    log_event("campaign_resumed" if resume else "campaign_started", settings=current_settings)
    telemetry = _TelemetryJournal(
        telemetry_path, destination, telemetry_interval_seconds
    )
    telemetry.start()
    active_segment_started = time.monotonic()
    print("[setup] applying initial cooldown policy", file=sys.stderr, flush=True)
    session["initial_cooldown"] = _cooldown(
        cooldown_until_c, cooldown_seconds, cooldown_max_seconds
    )
    print(
        f"[setup] initial cooldown: {session['initial_cooldown']['status']} "
        f"({session['initial_cooldown']['elapsed_seconds']:.1f} s)",
        file=sys.stderr, flush=True,
    )
    checkpoint()

    for warmup_index in range(1, warmups + 1):
        for scenario in ordered("warmup", warmup_index):
            if already_handled("warmup", warmup_index, scenario):
                continue
            print(
                f"[warmup {warmup_index}/{warmups}] {scenario.name} starting",
                file=sys.stderr, flush=True,
            )
            run_id, run_dir = dated_run_directory("warmups", warmup_index, scenario)
            command = _analysis_command(
                scenario, run_dir / "products", measurements_path, tle_path, eop_path, plot_path, limit
            )
            started_utc = _utc_text()
            telemetry.set_context(
                run_id=run_id, run_directory=run_dir,
                scenario=scenario.name, phase="warmup",
            )
            log_event("run_started", run_id=run_id, phase="warmup", round=warmup_index, scenario=scenario.name)
            _run_child(command, timeout_seconds, child_environment)
            finished_utc = _utc_text()
            record = {
                "run_id": run_id, "kind": "warmup", "round": warmup_index,
                "scenario": scenario.name, "status": "complete", "started_utc": started_utc,
                "finished_utc": finished_utc, "run_directory": str(run_dir), "command": command,
            }
            _atomic_write_json(run_dir / "run-record.json", record)
            telemetry.sample()
            telemetry.set_context(run_id=None, scenario=None, phase="idle")
            print(
                f"[warmup {warmup_index}/{warmups}] {scenario.name} complete",
                file=sys.stderr, flush=True,
            )
            execution = {
                **record, "cooldown": {"status": "pending"},
            }
            session["execution_order"].append(execution)
            checkpoint()
            execution["cooldown"] = _cooldown(cooldown_until_c, cooldown_seconds, cooldown_max_seconds)
            print(
                f"[warmup {warmup_index}/{warmups}] cooldown "
                f"{execution['cooldown']['status']} ({execution['cooldown']['elapsed_seconds']:.1f} s)",
                file=sys.stderr, flush=True,
            )
            checkpoint()

    scenario_runs = {
        scenario.name: session["scenarios"][scenario.name]["runs"] for scenario in scenarios
    }
    consecutive_failures = 0
    repeat_index = 1
    stop_reason = None
    while True:
        active_elapsed = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
        if duration_seconds is None and repeats is not None and repeat_index > repeats:
            break
        if duration_seconds is not None and repeat_index > 2 and active_elapsed >= duration_seconds:
            break
        for scenario in ordered("measured", repeat_index):
            if already_handled("measured", repeat_index, scenario):
                continue
            sample = telemetry.sample()
            stop_reason = safety_reason(sample)
            if stop_reason is not None:
                break
            print(
                f"[measured {repeat_index}/{repeats or 'duration'}] {scenario.name} starting",
                file=sys.stderr, flush=True,
            )
            run_id, run_dir = dated_run_directory("runs", repeat_index, scenario)
            command = _analysis_command(
                scenario, run_dir / "products", measurements_path, tle_path, eop_path, plot_path, limit
            )
            started_utc = _utc_text()
            telemetry.set_context(
                run_id=run_id, run_directory=run_dir,
                scenario=scenario.name, phase="measured",
            )
            log_event("run_started", run_id=run_id, phase="measured", round=repeat_index, scenario=scenario.name)
            before = system_snapshot()
            operator_interrupted = False
            try:
                outputs, elapsed, stderr = _run_child(command, timeout_seconds, child_environment)
                run = _validate_run(outputs, elapsed)
                run.update({
                    "run_id": run_id, "status": "complete", "started_utc": started_utc,
                    "finished_utc": _utc_text(), "run_directory": str(run_dir),
                    "system_before": before, "system_after": system_snapshot(),
                    "repeat": repeat_index, "command": command, "stderr": stderr,
                })
                scenario_runs[scenario.name].append(run)
                record = run
                consecutive_failures = 0
            except KeyboardInterrupt:
                operator_interrupted = True
                record = {
                    "run_id": run_id, "status": "interrupted", "started_utc": started_utc,
                    "finished_utc": _utc_text(), "run_directory": str(run_dir),
                    "kind": "measured", "repeat": repeat_index, "scenario": scenario.name,
                    "command": command, "reason": "operator interrupt",
                    "system_before": before, "system_after": system_snapshot(),
                }
                session.setdefault("interruptions", []).append(record)
            except Exception as exc:
                consecutive_failures += 1
                record = {
                    "run_id": run_id, "status": "failed", "started_utc": started_utc,
                    "finished_utc": _utc_text(), "run_directory": str(run_dir),
                    "kind": "measured", "repeat": repeat_index, "scenario": scenario.name,
                    "command": command, "error_type": type(exc).__name__, "error": str(exc),
                    "system_before": before, "system_after": system_snapshot(),
                }
                session["failures"].append(record)
            _atomic_write_json(run_dir / "run-record.json", record)
            telemetry.sample()
            telemetry.set_context(run_id=None, scenario=None, phase="idle")
            completed = record["status"] == "complete"
            print(
                f"[measured {repeat_index}/{repeats or 'duration'}] {scenario.name} "
                f"{record['status']} (temperature={record['system_after'].get('temperature_c')})",
                file=sys.stderr, flush=True,
            )
            execution = {
                "kind": "measured", "round": repeat_index, "run_id": run_id,
                "scenario": scenario.name, "status": record["status"], "command": command,
                "started_utc": record["started_utc"], "finished_utc": record["finished_utc"],
                "run_directory": str(run_dir), "cooldown": {"status": "pending"},
            }
            session["execution_order"].append(execution)
            session["active_elapsed_seconds"] = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
            active_segment_started = time.monotonic()
            log_event(
                "run_completed" if completed else
                ("run_interrupted" if operator_interrupted else "run_failed"),
                **execution,
            )
            checkpoint()
            if operator_interrupted:
                stop_reason = "operator interrupt"
                break
            if not completed and (not continue_on_error or consecutive_failures >= max_consecutive_failures):
                stop_reason = (
                    f"run failure; consecutive failures={consecutive_failures}, "
                    f"continue_on_error={continue_on_error}"
                )
                break
            execution["cooldown"] = _cooldown(cooldown_until_c, cooldown_seconds, cooldown_max_seconds)
            print(
                f"[measured {repeat_index}/{repeats or 'duration'}] cooldown "
                f"{execution['cooldown']['status']} ({execution['cooldown']['elapsed_seconds']:.1f} s)",
                file=sys.stderr, flush=True,
            )
            checkpoint()
        if stop_reason is not None:
            break
        repeat_index += 1

    all_consistent = True
    for scenario in scenarios:
        runs = scenario_runs[scenario.name]
        if not runs:
            all_consistent = False
            continue
        consistency = _check_repeat_consistency(runs)
        all_consistent &= consistency["all_consistent"]
        scenario_report = session["scenarios"][scenario.name]
        scenario_report["summary"] = _summarize_runs(runs)
        scenario_report["scientific_repeat_consistency"] = consistency
        if collect_perf:
            print(f"[perf] {scenario.name} starting", file=sys.stderr, flush=True)
            perf_dir = destination / "perf" / scenario.name
            perf_dir.mkdir(parents=True, exist_ok=True)
            perf_command = _analysis_command(
                scenario, perf_dir / "outputs", measurements_path, tle_path, eop_path,
                plot_path, limit, benchmark=False,
            )
            scenario_report["hardware_counters"] = _perf_run(
                perf_command, perf_dir / "perf-stat.csv", timeout_seconds,
                child_environment,
            )
            print(
                f"[perf] {scenario.name}: {scenario_report['hardware_counters']['status']}",
                file=sys.stderr, flush=True,
            )
        checkpoint()

    enough_successful_runs = all(len(runs) >= 2 for runs in scenario_runs.values())
    all_consistent &= enough_successful_runs
    session["scientific_outputs_consistent"] = all_consistent
    session["system_end"] = system_snapshot()
    session["active_elapsed_seconds"] = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
    session["status"] = "complete" if stop_reason is None and all_consistent else "stopped"
    session["stop_reason"] = stop_reason
    session["finished_utc"] = _utc_text()
    telemetry.set_context(run_id=None, scenario=None, phase="finished")
    telemetry.stop()
    csv_reports = _write_csv_reports(session, destination)
    session["tabular_reports"] = {
        name: {**_artifact_record(path)} for name, path in csv_reports.items()
    }
    report_path = destination / "benchmark-session.json"
    _atomic_write_json(report_path, session)
    checkpoint()
    log_event("campaign_finished", status=session["status"], stop_reason=stop_reason)
    session["report_path"] = str(report_path)
    return session
