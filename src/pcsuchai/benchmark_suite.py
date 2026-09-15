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
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from array import array

from .benchmark import _temperature_c, _throttled, runtime_metadata, sha256_file, system_snapshot
from .retention import compress_retained_file, deduplicate_products, snapshot_inputs, snapshot_sources
from .run_lock import inherited_lock_fds, serialized_run
from .worker import managed_analysis_execution
from .errors import ScientificValidationError, WorkerExecutionError, WorkerProtocolError, failure_classification


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

    from .observations import firmware_throttling
    throttling = firmware_throttling()
    snapshot = {
        "captured_utc": _utc_text(),
        "temperature_c": _temperature_c(),
        "throttled": hex(throttling["value"]) if throttling["status"] == "available" else None,
        "throttling_observation": throttling,
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
        "used_memory_bytes", "swap_used_bytes", "load_1m", "disk_free_bytes", "throttled", "segment_id",
        "observations_json", "elapsed_anchor_monotonic_seconds",
    )

    def __init__(
        self, path: Path, storage_path: Path, interval_seconds: float,
        elapsed_offset: float = 0.0,
        native_memory_interval_seconds: float = 10.0,
        maximum_temperature_c: float | None = None,
        require_temperature_sensor: bool = False,
    ) -> None:
        self.path = path
        self.storage_path = storage_path
        self.interval_seconds = interval_seconds
        self.started = time.monotonic()
        self.elapsed_offset = elapsed_offset
        self.segment_id = _utc_path_stamp()
        self.error: Exception | None = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.context = {"run_id": None, "run_directory": None, "scenario": None, "phase": "idle"}
        self.thread: threading.Thread | None = None
        self.stopped = False
        from .observations import ObservationSampler
        self.observations = ObservationSampler(native_memory_interval_seconds)
        self.worker_pid: int | None = None
        self.perf_pid: int | None = None
        self.maximum_temperature_c = maximum_temperature_c
        self.require_temperature_sensor = require_temperature_sensor
        self.thermal_policy_stop = None

    def set_launched_process(self, pid: int, *, perf_wrapper: bool) -> None:
        """Keep perf's supervisor PID distinct from the actual analysis worker."""

        self.perf_pid = pid if perf_wrapper else None
        self.worker_pid = None if perf_wrapper else pid

    def set_context(
        self, *, run_id: str | None, run_directory: Path | None = None,
        scenario: str | None, phase: str,
    ) -> None:
        """Label future samples with the active workload."""

        with self.write_lock, self.lock:
            self.context = {
                "run_id": run_id, "run_directory": str(run_directory) if run_directory else None,
                "scenario": scenario, "phase": phase,
            }

    def sample(self) -> dict:
        """Append one sample immediately and return it for safety checks."""

        if self.error is not None:
            raise RuntimeError("raw system telemetry persistence failed") from self.error
        record = _telemetry_snapshot(self.storage_path)
        record["campaign_elapsed_seconds"] = self.elapsed_offset + time.monotonic() - self.started
        record["elapsed_anchor_monotonic_seconds"] = self.started - self.elapsed_offset
        record["segment_id"] = self.segment_id
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
            if self.perf_pid is not None and self.worker_pid is None:
                try:
                    import psutil
                    for child in psutil.Process(self.perf_pid).children(recursive=True):
                        arguments = child.cmdline()
                        if "pcsuchai" in arguments and "analyze" in arguments:
                            self.worker_pid = child.pid
                            break
                except (psutil.Error, OSError):
                    pass  # Unknown worker identity remains missing, never perf's PID.
            record["observations_json"] = self.observations.capture_json(self.storage_path, worker_pid=self.worker_pid)
            if "throttling_observation" in record:
                readings = json.loads(record["observations_json"])
                readings.setdefault("board", {})["throttling_flags"] = record.pop("throttling_observation")
                record["observations_json"] = json.dumps(readings, separators=(",", ":"), allow_nan=False)
            with self.lock:
                record.update(self.context)
                if record.get("phase") in ("warmup", "measured") and self.thermal_policy_stop is None:
                    from .thermal import thermal_safety_reason
                    reason = thermal_safety_reason(record.get("temperature_c"), self.maximum_temperature_c,
                                                   self.require_temperature_sensor)
                    if reason:
                        self.thermal_policy_stop = {"reason": reason, "captured_utc": record.get("captured_utc"),
                                                    "campaign_elapsed_seconds": record["campaign_elapsed_seconds"],
                                                    "segment_id": self.segment_id, "run_id": record.get("run_id"),
                                                    "phase": record.get("phase"), "temperature_c": record.get("temperature_c"),
                                                    "scope": "sampled_board_soc; finish active job then stop", "source": "retained board telemetry"}
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
                try:
                    self.sample()
                except Exception as exc:
                    self.error = exc
                    self.stop_event.set()
                    break

        self.thread = threading.Thread(target=loop, name="pcsuchai-telemetry", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Join the sampler and append at most one final sample, even on failure."""

        if self.stopped:
            return
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
        # Even an unwritable final sample must not leave a live thread or cause
        # a later cleanup callback to recreate a finalized timeline.
        self.stopped = True
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
    """Identify executable source independently of Git and generated metadata.

    Distribution metadata is acquired separately as runtime provenance. Its
    build-dependent file lists must not change identical source's identity
    between an installed checkout and a clean clone/release archive.
    """

    source_suffixes = {".py", ".sh", ".json", ".txt", ".patch", ".npz", ".md"}
    files = sorted({
        path for base in ("src", "scripts", "configs", "requirements", "packaging")
        for path in (project_root / base).rglob("*")
        if path.is_file() and path.suffix in source_suffixes and "__pycache__" not in path.parts
        and not any(part.endswith((".egg-info", ".dist-info")) for part in path.relative_to(project_root).parts[:-1])
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
        "passed": status in ("fixed_delay_complete", "target_reached"),
    }


def parse_perf_stat(path: str | Path) -> dict[str, float | str | None]:
    """Return legacy event values; full accounting uses ``parse_counter_records``."""

    from .counters import parse_counter_records
    return {item["event"]: item["reported_value"] for item in parse_counter_records(path, no_scale=False)["events"]}


def _analysis_command(
    scenario: BenchmarkScenario,
    output_dir: Path,
    measurements: Path,
    tle: Path,
    eop: Path,
    plot_config: Path | None,
    limit: int | None,
    benchmark: bool = True,
    selection_method: str = "prefix",
    observation_level: str = "normal",
    stage_interval_seconds: float = 0.05,
    native_memory_interval_seconds: float = 10.0,
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
    if selection_method != "prefix":
        command.extend(("--selection-method", selection_method))
    command.extend(("--observation-level", observation_level, "--stage-interval-seconds", str(stage_interval_seconds),
                    "--native-memory-interval-seconds", str(native_memory_interval_seconds)))
    return command


def _run_child(
    command: list[str], timeout_seconds: float, environment: dict[str, str] | None = None,
    *, on_launch=None,
) -> tuple[dict, float, str]:
    """Time launch through worker exit, retaining separate log-finalization cost.

    The returned duration includes process creation/import/science/output writes
    in the worker. Parent log setup, fsync, JSON parsing and retention are outside
    it. A timing record is saved even when the worker fails or times out.
    """

    started = time.perf_counter()
    output_dir = Path(command[command.index("--output-dir") + 1])
    log_dir = output_dir.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path, stderr_path = log_dir / "stdout.log", log_dir / "stderr.log"
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        setup_seconds = time.perf_counter() - started
        worker_started = time.perf_counter()
        process = None
        try:
            process = subprocess.Popen(
                command, stdout=stdout, stderr=stderr, env=environment,
                pass_fds=inherited_lock_fds(environment), start_new_session=True,
            )
            if on_launch is not None:
                on_launch(process.pid)
            process.wait(timeout=timeout_seconds)
        finally:
            if process is not None and process.poll() is None:
                # Never orphan a timed-out/interrupted worker or infer exit
                # merely from an observation deadline. Stop this exact handle.
                # Popen created this exact process group; terminate any analysis
                # descendants too (perf can otherwise orphan its Python child).
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            elapsed = time.perf_counter() - worker_started
            finalization_started = time.perf_counter()
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
            _atomic_write_json(log_dir / "child-timing.json", {
                "schema_version": 1,
                "scope": "supervisor_observed_worker_process",
                "clock": "time.perf_counter",
                "setup_seconds": setup_seconds,
                "worker_launch_to_exit_seconds": elapsed,
                "log_flush_seconds": time.perf_counter() - finalization_started,
                "worker_boundary": "immediately before Popen through wait/exception cleanup and observed exit",
                "worker_pid": process.pid if process is not None else None,
                "return_code": process.returncode if process is not None else None,
                "includes": ["process_launch", "imports", "science", "worker_output_finalization", "worker_exit"],
                "excludes": ["parent_log_setup", "parent_log_flush", "parent_log_parsing", "retention"],
            })
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if process.returncode != 0:
        raise WorkerExecutionError(
            f"benchmark child failed ({process.returncode}): {' '.join(command)}\n"
            f"complete logs: {stdout_path}, {stderr_path}\n"
            f"stdout:\n{stdout_text[-2000:]}\nstderr:\n{stderr_text[-4000:]}"
        )
    try:
        outputs = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise WorkerProtocolError(f"benchmark child returned invalid JSON; see {stdout_path}") from exc
    return outputs, elapsed, stderr_text


def _retain_run(run_dir: Path, destination: Path) -> dict:
    """Retain all closed bytes and measure compression, sharing and allocation.

    File allocation is attributed only to new product backing inodes and all
    non-product attempt files. Later record/checkpoint/directory costs and peak
    temporary allocation are explicitly excluded, not silently guessed.
    """

    from .storage import filesystem_capacity, inventory_storage

    started = time.perf_counter()
    compressed = []
    compression_records = []

    def compress(path: Path) -> None:
        """Record the complete verified compression call, including hashing/fsync."""

        original_bytes = path.stat().st_size
        compression_started = time.perf_counter()
        saved = compress_retained_file(path, remove_original=True)
        elapsed = time.perf_counter() - compression_started
        compressed.append(str(saved))
        compressed_bytes = saved.stat().st_size
        compression_records.append({"path": str(saved), "original_bytes": original_bytes,
                                    "compressed_bytes": compressed_bytes, "wall_seconds": elapsed,
                                    "compressed_to_original_ratio": compressed_bytes / original_bytes if original_bytes else None,
                                    "unit": "bytes_and_seconds", "scope": "attempt_closed_raw_file",
                                    "source": "stat/perf_counter/verified_gzip", "status": "available"})
    for path in (run_dir / "stdout.log", run_dir / "stderr.log", run_dir / "system-telemetry.csv", run_dir / "perf-stat.csv"):
        if path.is_file():
            compress(path)
    products = run_dir / "products"
    # Failed/interrupted children may leave a plain, partial raw sample journal.
    if products.is_dir():
        for path in products.glob("*.samples.csv"):
            if not path.with_name(path.name + ".gz").exists():
                compress(path)
    sharing_started = time.perf_counter()
    storage = deduplicate_products(products, destination / "artifact-store")
    sharing_seconds = time.perf_counter() - sharing_started
    nonproducts = [path for path in run_dir.rglob("*") if path.is_file() and not path.is_symlink() and products not in path.parents]
    stats = [path.stat() for path in nonproducts]
    # One inode can have multiple names. Attribute its blocks once.
    unique = {(stat.st_dev, stat.st_ino): stat for stat in stats}
    allocated = storage["new_product_allocated_bytes"]
    if allocated is not None and all(hasattr(stat, "st_blocks") for stat in unique.values()):
        allocated += sum(stat.st_blocks * 512 for stat in unique.values())
    else:
        allocated = None
    capacity_after = filesystem_capacity(destination)
    capacity_before = None
    intent_path = run_dir / "attempt-intent.json"
    if intent_path.is_file():
        capacity_before = json.loads(intent_path.read_text()).get("capacity_before_attempt")
    growth = inode_growth = None
    if isinstance(capacity_before, dict) and capacity_before.get("status") == capacity_after.get("status") == "available" and capacity_before.get("device_id") == capacity_after.get("device_id"):
        growth = capacity_before["free_bytes"] - capacity_after["free_bytes"]
        inode_growth = capacity_before["free_inodes"] - capacity_after["free_inodes"]
    return {
        **storage, "compressed_raw_files": compressed,
        "compression_records": compression_records,
        "parent_compression_original_bytes": sum(record["original_bytes"] for record in compression_records),
        "parent_compression_saved_bytes": sum(record["compressed_bytes"] for record in compression_records),
        "parent_compression_file_count": len(compression_records),
        "compression_wall_seconds": sum(record["wall_seconds"] for record in compression_records),
        "sharing_wall_seconds": sharing_seconds,
        "new_retained_file_allocated_bytes": allocated,
        "new_retained_file_inodes": storage["new_product_inodes"] + len(unique),
        "attempt_tree_at_retention": inventory_storage(run_dir, scope="retained_attempt_tree_on_target"),
        "capacity_before_attempt": capacity_before,
        "capacity_after_retention": capacity_after,
        "observed_filesystem_growth_bytes": growth,
        "observed_filesystem_growth_inodes": inode_growth,
        "filesystem_growth_scope": "whole retention filesystem between intent preparation and retention audit; includes concurrent activity, excludes later commit/finalization; negative changes remain negative",
        "cost_scope": "parent retention after worker exit; included in committed cycle; excludes worker-internal compression",
        "growth_limit": "file-block lower bound; excludes later record/checkpoint/directory allocation, setup/finalization and temporary peak",
        "retention_wall_seconds": time.perf_counter() - started,
    }


def _retain_attempt(record: dict, run_dir: Path, destination: Path) -> bool:
    """Record failed retention separately from science and preserve partial bytes.

    True means retention completed; false requires stopping further work even
    under continue-on-error. Metadata commits can themselves fail on a genuinely
    full filesystem: durable intents/partial files remain for later recovery,
    not an invented successful terminal or a guarantee of power-loss durability.
    """

    started = time.perf_counter()
    try:
        record["storage"] = _retain_run(run_dir, destination)
        return True
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "error": str(exc),
                   "error_errno": getattr(exc, "errno", None),
                   "failure_class": failure_classification(exc)}
        record["storage"] = {"status": "failed", "retention_completed": False,
                             "retention_failure": failure,
                             "retention_wall_seconds": time.perf_counter() - started,
                             "timer_scope": "attempted_parent_retention_call_including_partial_work_not_successful_finalization",
                             "raw_records_pruned": False,
                             "recovery_policy": "retain original/verified compressed/partial files; no automatic retention retry"}
        record["scientific_execution_status"] = record["status"]
        if record["status"] == "complete":
            record.update(status="failed", failure_phase="retention", **failure)
        else:
            # The primary computation/interrupt error must not disappear when
            # its independent retention also fails.
            record["retention_failure"] = failure
        return False


def _validate_run(outputs: dict, external_wall_seconds: float) -> dict:
    """Validate required products and collect their hashes and stage records."""

    if not outputs.get("manifest_json") or not Path(outputs["manifest_json"]).is_file():
        raise ScientificValidationError("benchmark run is missing artifacts: manifest_json")
    manifest = json.loads(Path(outputs["manifest_json"]).read_text())
    minimal = manifest.get("instrumentation", {}).get("level") == "minimal"
    required = (
        "positions_csv", "particle_map_png", "manifest_json", "benchmark_json",
        "magnetic_positions_csv", "magnetic_particle_map_png", "footpoint_particle_map_png",
        "raw_products_npz",
    ) + (() if minimal else ("raw_benchmark_samples",))
    missing = [name for name in required if not outputs.get(name) or not Path(outputs[name]).is_file()]
    if missing:
        raise ScientificValidationError(f"benchmark run is missing artifacts: {', '.join(missing)}")
    if manifest["valid_positions"] <= 0 or manifest["observations"] <= 0:
        raise ScientificValidationError("benchmark run produced no valid orbit observations")
    from .product_validation import validate_pipeline_images
    image_validation = validate_pipeline_images(
        manifest, outputs["raw_products_npz"], tuple(outputs.get("plot_selection_files", [])),
    )
    if not image_validation["passed"]:
        raise ScientificValidationError("benchmark run failed saved-image scientific selection/dimension/context validation")
    stages = json.loads(Path(outputs["benchmark_json"]).read_text())
    artifacts = {name: _artifact_record(outputs[name]) for name in required}
    configured = [_artifact_record(path) for path in outputs.get("configured_plot_files", [])]
    selections = [_artifact_record(path) for path in outputs.get("plot_selection_files", [])]
    if len(selections) != len(configured):
        raise ScientificValidationError("each configured plot must retain its complete raw selection")
    return {
        "external_wall_seconds": external_wall_seconds,
        "observations": manifest["observations"],
        "valid_positions": manifest["valid_positions"],
        "valid_magnetic_positions": manifest["valid_magnetic_positions"],
        "artifacts": artifacts,
        "configured_plot_artifacts": configured,
        "plot_selection_artifacts": selections,
        "output_bytes": sum(item["size_bytes"] for item in artifacts.values())
        + sum(item["size_bytes"] for item in configured + selections),
        "stages": stages,
        "image_validation": image_validation,
        "instrumentation": manifest.get("instrumentation"),
    }


def _load_run(record: dict) -> dict:
    """Read a complete per-run record without keeping it in campaign RAM."""

    if "record_path" in record:
        record = json.loads(Path(record["record_path"]).read_text(encoding="utf-8"))
    if record.get("cycle_timing_path"):
        path = Path(record["cycle_timing_path"])
        if path.is_file():
            cycle = json.loads(path.read_text(encoding="utf-8"))
            if cycle["run_id"] != record["run_id"]:
                raise ValueError("cycle timing identity does not match the immutable attempt")
            record = {**record, "full_cycle_seconds": cycle["full_cycle_seconds"], "cycle_timing": cycle}
        else:
            record = {**record, "full_cycle_seconds": None, "cycle_timing_status": "uncommitted"}
    return record  # Legacy records retain their original, narrower boundaries.


def _commit_cycle_timing(run_dir: Path, run_id: str, cycle_started: float) -> dict:
    """Save job latency after run-record, terminal event and checkpoint commits.

    The observation sidecar's own write follows the boundary: measurement cannot
    record the completion of its own final byte. That write still contributes
    to campaign elapsed time/throughput. Recovery and session setup/shutdown are
    separate costs. A power loss before this sidecar leaves a valid attempt
    with explicitly unavailable cycle timing, never an invented duration.
    """

    value = {
        "schema_version": 2, "run_id": run_id, "captured_utc": _utc_text(),
        "clock": "time.perf_counter", "unit": "seconds", "scope": "supervisor_job_cycle",
        "full_cycle_seconds": time.perf_counter() - cycle_started,
        "includes": ["scheduling_safety_checks", "attempt_directory_setup", "worker_execution",
                     "product_validation", "per_attempt_observations", "retention",
                     "run_record_commit", "terminal_event_commit", "checkpoint_commit"],
        "excludes": ["thermal_recovery", "session_validation_setup", "persistent_worker_startup_shutdown",
                     "session_reporting", "cycle_timing_sidecar_write"],
    }
    path = run_dir / "cycle-timing.json"
    if path.exists():
        raise FileExistsError(f"cycle timing already committed: {path}")
    _atomic_write_json(path, value)
    return value


def _summarize_runs(runs: list[dict]) -> dict:
    """Aggregate whole-process and per-stage measurements across repeats."""

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
    values: dict[str, dict[str, array]] = {}
    wall_values, output_values, cycle_values = array("d"), array("d"), array("d")
    for reference in runs:
        run = _load_run(reference)
        wall_values.append(run["external_wall_seconds"])
        output_values.append(run["output_bytes"])
        if run.get("full_cycle_seconds") is not None:
            cycle_values.append(run["full_cycle_seconds"])
        for stage in run["stages"]:
            metrics = values.setdefault(stage["stage"], {})
            for field in stage_fields:
                if stage.get(field) is not None:
                    metrics.setdefault(field, array("d")).append(float(stage[field]))
    stage_summary = {
        name: {field: _statistics(samples) for field, samples in metrics.items()}
        for name, metrics in sorted(values.items())
    }
    return {
        "external_wall_seconds": _statistics(wall_values),
        "full_cycle_seconds": _statistics(cycle_values),
        "output_bytes": _statistics(output_values),
        "stages": stage_summary,
    }


def _check_repeat_consistency(runs: list[dict]) -> dict:
    """Require deterministic scientific tables across identical repeats."""

    roles = ("positions_csv", "magnetic_positions_csv")
    result = {}
    role_hashes = {role: [] for role in roles}
    for reference in runs:
        run = _load_run(reference)
        for role in roles:
            role_hashes[role].append(run["artifacts"][role]["sha256"])
    for role, hashes in role_hashes.items():
        result[role] = {"consistent": len(set(hashes)) == 1, "sha256": hashes}
    result["all_consistent"] = all(item["consistent"] for item in result.values())
    return result


def _write_csv_reports(session: dict, destination: Path) -> dict[str, str]:
    """Write operator-friendly summaries without discarding the complete JSON."""

    run_path = destination / "run-timeseries.csv"
    with run_path.open("w", encoding="utf-8", newline="") as handle:
        columns = [
            "run_id", "started_utc", "finished_utc", "run_directory",
            "scenario", "repeat", "external_wall_seconds", "full_cycle_seconds", "output_bytes",
            "temperature_before_c", "temperature_after_c", "memory_available_before_bytes",
            "memory_available_after_bytes", "cpu_frequency_before_mhz",
            "cpu_frequency_after_mhz", "throttled_before", "throttled_after",
            "valid_positions", "valid_magnetic_positions",
        ]
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for scenario, report in session["scenarios"].items():
            for reference in report["runs"]:
                run = _load_run(reference)
                before, after = run["system_before"], run["system_after"]
                writer.writerow({
                    "run_id": run.get("run_id"),
                    "started_utc": run.get("started_utc"),
                    "finished_utc": run.get("finished_utc"),
                    "run_directory": run.get("run_directory"),
                    "scenario": scenario, "repeat": run["repeat"],
                    "external_wall_seconds": run["external_wall_seconds"],
                    "full_cycle_seconds": run.get("full_cycle_seconds"),
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
            for reference in report["runs"]:
                run = _load_run(reference)
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
        executable, "stat", "--no-scale", "--no-big-num", "-x", ";", "-o", str(perf_path), "-e",
        "cycles,instructions,task-clock,context-switches,page-faults", "--", *command,
    ]
    stdout_path, stderr_path = perf_path.with_suffix(".stdout.log"), perf_path.with_suffix(".stderr.log")
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        try:
            result = subprocess.run(
                perf_command, stdout=stdout, stderr=stderr, timeout=timeout_seconds,
                check=False, env=environment,
                pass_fds=inherited_lock_fds(environment),
            )
        finally:
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
    logs = {
        "stdout": str(compress_retained_file(stdout_path, remove_original=True)),
        "stderr": str(compress_retained_file(stderr_path, remove_original=True)),
    }
    if result.returncode != 0:
        return {
            "status": "unavailable", "reason": f"perf failed; complete logs: {logs}",
            "return_code": result.returncode, "logs": logs,
        }
    from .counters import parse_counter_records
    accounting = parse_counter_records(perf_path)
    return {
        "status": "available", "counters": parse_perf_stat(perf_path),
        "logs": logs, "accounting": accounting, "command": perf_command,
        "experiment_classification": "legacy_single_counter_diagnostic",
        "simultaneous_group": False,
    }


@serialized_run
@managed_analysis_execution
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
    thermal_policy: dict | None = None,
    ordering: str = "randomized",
    session_index: int = 1,
    thread_policy: str = "stock",
    process_mode: str = "fresh",
    selection_method: str = "prefix",
    observation_level: str = "normal",
    stage_interval_seconds: float = 0.05,
    native_memory_interval_seconds: float = 10.0,
    _executor=None,
    scenario_pairs: tuple[str, ...] | None = None,
    thermal_between_attempts: bool = True,
    stop_requested=None,
    counter_group: tuple[str, ...] | None = None,
    minimum_counter_coverage_percent: float = 95.0,
    require_temperature_sensor: bool = False,
) -> dict:
    """Run a durable finite or duration-based clean-process benchmark campaign."""

    if duration_seconds is None and (repeats is None or repeats < 1):
        raise ValueError("benchmark suite requires positive attempts or a duration")
    if repeats is not None and repeats < 1:
        raise ValueError("repeats must be positive when specified")
    if duration_seconds is not None and repeats is not None:
        raise ValueError("choose either fixed attempts or duration, not both")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if telemetry_interval_seconds <= 0 or minimum_free_bytes < 0 or max_consecutive_failures < 1:
        raise ValueError("telemetry interval/failure limit must be positive and free space nonnegative")
    if warmups < 0 or cooldown_seconds < 0 or cooldown_max_seconds < 0 or timeout_seconds <= 0:
        raise ValueError("warmups/cooldown must be nonnegative and timeout positive")
    from .thermal import ThermalPolicy, acquire_thermal_condition, thermal_safety_reason
    import math
    if type(require_temperature_sensor) is not bool:
        raise ValueError("require_temperature_sensor must be boolean")
    if maximum_temperature_c is not None and (type(maximum_temperature_c) not in (int, float) or not math.isfinite(maximum_temperature_c) or maximum_temperature_c <= 0):
        raise ValueError("maximum_temperature_c must be finite and positive")
    from .experiment import balanced_order, thread_environment

    recovery_policy = ThermalPolicy(**thermal_policy) if thermal_policy is not None else None
    if observation_level not in ("minimal", "normal", "detailed"):
        raise ValueError("invalid observation level")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in (stage_interval_seconds, native_memory_interval_seconds)):
        raise ValueError("observation intervals must be finite and positive")
    if isinstance(minimum_counter_coverage_percent, bool) or not isinstance(minimum_counter_coverage_percent, (int, float)) or not math.isfinite(minimum_counter_coverage_percent) or not 0 < minimum_counter_coverage_percent <= 100:
        raise ValueError("counter coverage must be finite and in (0, 100]")
    if selection_method not in ("full", "prefix", "spread"):
        raise ValueError("invalid workload selection method")
    if selection_method == "full" and limit is not None:
        raise ValueError("full selection requires limit=None")
    if official and selection_method == "spread":
        raise ValueError("spread selections require an exact variant certificate; legacy full-code certificates do not cover them")
    if recovery_policy is not None and (cooldown_until_c is not None or cooldown_seconds):
        raise ValueError("choose a stable thermal policy or legacy cooldown, not both")
    if process_mode == "persistent" and collect_perf:
        raise ValueError("use a separate counter experiment after the persistent worker closes")
    if counter_group is not None and (process_mode != "fresh" or collect_perf):
        raise ValueError("dedicated grouped counters require fresh execution without legacy collect_perf")
    if counter_group is not None:
        from .counter_experiment import counter_command
        counter_command([], counter_group, Path("perf-stat.csv"))
    if ordering not in ("randomized", "balanced") or session_index < 1:
        raise ValueError("invalid ordering/session index")
    allowed_pairs = {f"{orbit}-{mag}" for orbit in ("astropy", "skyfield") for mag in ("aacgmv2", "apexpy")}
    if scenario_pairs is not None and (not scenario_pairs or any(not isinstance(pair, str) or pair not in allowed_pairs for pair in scenario_pairs) or len(set(scenario_pairs)) != len(scenario_pairs)):
        raise ValueError("scenario_pairs must be unique supported complete backend pairs")
    if type(thermal_between_attempts) is not bool:
        raise ValueError("thermal_between_attempts must be boolean")
    destination = Path(output_dir)
    if resume:
        if not destination.is_dir():
            raise ValueError(f"cannot resume missing benchmark directory: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    measurements_path, tle_path, eop_path = map(Path, (measurements, tle, eop))
    plot_path = Path(plot_config) if plot_config is not None else None
    resolved_root = Path(project_root).resolve()
    child_environment = thread_environment(thread_policy, os.environ.copy())
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
        if scenario_pairs is not None and set(scenario_pairs) != allowed_pairs:
            raise ValueError("official legacy benchmark requires the complete four-pair matrix")
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

    scenarios = tuple(BenchmarkScenario(*pair.split("-", 1)) for pair in scenario_pairs) if scenario_pairs is not None else tuple(
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
        **({"require_temperature_sensor": True} if require_temperature_sensor else {}),
        "continue_on_error": continue_on_error,
        "max_consecutive_failures": max_consecutive_failures,
        "artifact_retention": "all",
        "raw_compression": "verified_gzip_and_npz",
        "product_storage": "lossless_sha256_hardlinks",
        "stop_rule": "attempts_per_pair" if duration_seconds is None else "deadline_between_attempts",
        "duration_clock": "measured_campaign_after_warmups_and_recovery_including_retention_and_recovery",
        "timer_boundary_version": 2,
        "thermal_policy": thermal_policy,
        "ordering": ordering, "session_index": session_index, "thread_policy": thread_policy,
        "process_mode": process_mode,
        "selection_method": selection_method,
        "observation_level": observation_level,
        "stage_interval_seconds": stage_interval_seconds,
        "native_memory_interval_seconds": native_memory_interval_seconds,
        "scenario_pairs": list(scenario_pairs) if scenario_pairs is not None else None,
        "thermal_between_attempts": thermal_between_attempts,
        "counter_group": list(counter_group) if counter_group is not None else None,
        "minimum_counter_coverage_percent": minimum_counter_coverage_percent,
    }
    new_session = {
        "schema_version": 3,
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
        if duration_seconds is not None and session.get("status") == "running":
            session["duration_clock_status"] = "unavailable_after_abrupt_uncommitted_segment"
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
        session["input_snapshots"] = snapshot_inputs(inputs, destination / "inputs")
        session["source_snapshot"] = snapshot_sources(
            resolved_root, current_source, destination / "source-snapshot.tar.gz"
        )
        _atomic_write_json(destination / "input-snapshots.json", session["input_snapshots"])

    def checkpoint() -> None:
        from .experiment_control import session_attempt_counts
        session["attempt_counts"] = session_attempt_counts(session)
        _atomic_write_json(checkpoint_path, session)

    def log_event(event_type: str, **values: object) -> None:
        _append_jsonl(
            event_path, {"recorded_utc": _utc_text(), "event": event_type, **values}
        )

    def ordered(kind: str, round_number: int) -> list[BenchmarkScenario]:
        if ordering == "balanced":
            by_name = {scenario.name: scenario for scenario in scenarios}
            return [by_name[name] for name in balanced_order(
                list(by_name), session_index, round_number,
                seed if kind == "measured" else seed + 1,
            )]
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
        return (kind, round_number, scenario.name) in handled

    if resume:
        from .recovery import reconcile_attempts

        def verify_recovered_record(record: dict) -> None:
            """Check recovered success bytes and actual saved-image selections."""

            if record.get("kind") == "warmup":
                # Older warm-up records did not retain an artifact index. Their
                # success cannot be upgraded to verified science from a label.
                if not record.get("artifacts"):
                    raise ValueError("warm-up lacks a verifiable artifact index")
            artifacts = record["artifacts"]
            configured = record.get("configured_plot_artifacts", [])
            selections = record.get("plot_selection_artifacts", [])
            for artifact in [*artifacts.values(), *configured, *selections]:
                path = Path(artifact["path"])
                if not path.resolve().is_relative_to(destination):
                    raise ValueError("recovered artifact escapes its experiment block")
                if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                    raise ValueError(f"recovered artifact missing/modified: {path}")
            outputs = {key: item["path"] for key, item in artifacts.items()}
            outputs.update(configured_plot_files=[item["path"] for item in configured],
                           plot_selection_files=[item["path"] for item in selections])
            _validate_run(outputs, record.get("external_wall_seconds", 0.0))

        reconciled = reconcile_attempts(destination, session, verify_recovered_record)
        for execution in reconciled:
            log_event("attempt_reconciled", **execution)
        if reconciled:
            if duration_seconds is not None:
                session["duration_clock_status"] = "unavailable_after_abrupt_uncommitted_segment"
            session.setdefault("recovery_events", []).append({"recorded_utc": _utc_text(),
                                                               "run_ids": [item["run_id"] for item in reconciled]})
            checkpoint()

    handled = {
        (item.get("kind"), item.get("round"), item.get("scenario"))
        for item in session["execution_order"]
        if item.get("status") in ("complete", "failed", "interrupted")
    }

    def safety_reason(sample: dict) -> str | None:
        if sample["disk_free_bytes"] < minimum_free_bytes:
            return f"disk free space {sample['disk_free_bytes']} below limit {minimum_free_bytes}"
        latched = telemetry.thermal_policy_stop
        reason = latched["reason"] if latched else thermal_safety_reason(sample.get("temperature_c"), maximum_temperature_c,
                                                                        require_temperature_sensor)
        if reason:
            session["thermal_policy_stop"] = latched or {"reason": reason, "captured_utc": sample.get("captured_utc"),
                                                         "segment_id": sample.get("segment_id"), "phase": sample.get("phase"),
                                                         "temperature_c": sample.get("temperature_c"), "source": "retained board telemetry decision boundary",
                                                         "scope": "sampled_board_soc; no instantaneous protection guarantee"}
        return reason

    checkpoint()
    log_event("campaign_resumed" if resume else "campaign_started", settings=current_settings)
    counter_capability = None
    if counter_group is not None:
        from .counter_experiment import probe_counter_group
        counter_capability = probe_counter_group(
            counter_group, destination / "counter-capability" / _utc_path_stamp(), child_environment,
            minimum_counter_coverage_percent,
        )
        session.setdefault("counter_capabilities", []).append(counter_capability)
        checkpoint()
    _executor.start(destination / "workers" / _utc_path_stamp(), child_environment, timeout_seconds)
    session.setdefault("process_segments", []).append(_executor.metadata)
    checkpoint()
    telemetry = _TelemetryJournal(
        telemetry_path, destination, telemetry_interval_seconds,
        elapsed_offset=float(session.get("active_elapsed_seconds", 0.0)),
        native_memory_interval_seconds=native_memory_interval_seconds,
        maximum_temperature_c=maximum_temperature_c,
        require_temperature_sensor=require_temperature_sensor,
    )
    telemetry.worker_pid = _executor.metadata.get("pid")
    _executor.manage_cleanup(telemetry.stop)
    telemetry.start()
    active_segment_started = time.monotonic()
    stop_reason = ("cannot recover exact measured duration after abrupt exit; preserved attempts retained, start a new experiment for more work"
                   if session.get("duration_clock_status") == "unavailable_after_abrupt_uncommitted_segment" else None)

    def requested_stop() -> bool:
        """Observe an operator request only at safe complete-job boundaries."""

        return stop_requested is not None and stop_requested()

    def child_runner(command, timeout, environment):
        """Expose each actual fresh PID to the independently running sampler."""

        wrapped = counter_group is not None and counter_capability["status"] == "acceptable"
        if wrapped:
            from .counter_experiment import counter_command
            run_dir = Path(command[command.index("--output-dir") + 1]).parent
            command = counter_command(command, counter_group, run_dir / "perf-stat.csv")
        return _run_child(command, timeout, environment,
                          on_launch=lambda pid: telemetry.set_launched_process(pid, perf_wrapper=wrapped))

    def recover() -> dict:
        """Apply a requested condition; callers must check ``passed``."""

        if recovery_policy is None:
            return _cooldown(cooldown_until_c, cooldown_seconds, cooldown_max_seconds)
        recovery_dir = destination / "recovery"
        recovery_dir.mkdir(exist_ok=True)
        if not session.get("idle_baseline", {}).get("passed"):
            session["idle_baseline"] = acquire_thermal_condition(
                recovery_policy, recovery_dir / f"{_utc_path_stamp()}-baseline.csv",
                sensor=_temperature_c,
                cancelled=requested_stop,
            )
            checkpoint()
        baseline = session["idle_baseline"]
        if not baseline["passed"]:
            return baseline
        result = acquire_thermal_condition(
            recovery_policy, recovery_dir / f"{_utc_path_stamp()}-gate.csv",
            baseline_c=baseline["baseline_c"], sensor=_temperature_c,
            cancelled=requested_stop,
        )
        session.setdefault("recovery_records", []).append(result)
        return result

    print("[setup] applying initial cooldown policy", file=sys.stderr, flush=True)
    session["initial_cooldown"] = recover() if stop_reason is None else {
        "status": "not_started_unrecoverable_duration_clock", "passed": False, "elapsed_seconds": 0.0,
    }
    if not session["initial_cooldown"]["passed"]:
        stop_reason = stop_reason or f"unmet initial thermal condition: {session['initial_cooldown']['status']}"
    print(
        f"[setup] initial cooldown: {session['initial_cooldown']['status']} "
        f"({session['initial_cooldown']['elapsed_seconds']:.1f} s)",
        file=sys.stderr, flush=True,
    )
    checkpoint()

    for warmup_index in range(1, warmups + 1):
        if stop_reason is not None:
            break
        for scenario in ordered("warmup", warmup_index):
            if requested_stop():
                stop_reason = "operator graceful stop"
                break
            if already_handled("warmup", warmup_index, scenario):
                continue
            stop_reason = safety_reason(telemetry.sample())
            if stop_reason is not None:
                break
            print(
                f"[warmup {warmup_index}/{warmups}] {scenario.name} starting",
                file=sys.stderr, flush=True,
            )
            run_id, run_dir = dated_run_directory("warmups", warmup_index, scenario)
            command = _analysis_command(
                scenario, run_dir / "products", measurements_path, tle_path, eop_path, plot_path, limit,
                selection_method=selection_method,
                observation_level=observation_level, stage_interval_seconds=stage_interval_seconds,
                native_memory_interval_seconds=native_memory_interval_seconds,
            )
            started_utc = _utc_text()
            from .experiment_control import process_identity
            from .storage import filesystem_capacity
            _atomic_write_json(run_dir / "attempt-intent.json", {
                "run_id": run_id, "kind": "warmup", "round": warmup_index,
                "scenario": scenario.name, "started_utc": started_utc, "command": command,
                "supervisor_identity": process_identity(), "policy": "consumes_slot_if_interrupted",
                "capacity_before_attempt": filesystem_capacity(destination),
            })
            telemetry.set_context(
                run_id=run_id, run_directory=run_dir,
                scenario=scenario.name, phase="warmup",
            )
            log_event("run_started", run_id=run_id, phase="warmup", round=warmup_index, scenario=scenario.name)
            try:
                outputs, elapsed, _stderr = _executor.run(
                    command, timeout_seconds, child_environment, fresh_runner=child_runner
                )
                verified_warmup = _validate_run(outputs, elapsed)
            except BaseException as exc:
                telemetry.sample()
                telemetry.set_context(run_id=None, scenario=None, phase="idle")
                failure = {
                    "run_id": run_id, "kind": "warmup", "round": warmup_index,
                    "scenario": scenario.name, "status": "failed", "started_utc": started_utc,
                    "finished_utc": _utc_text(), "run_directory": str(run_dir),
                    "command": command, "error_type": type(exc).__name__, "error": str(exc),
                    "failure_class": failure_classification(exc),
                }
                _retain_attempt(failure, run_dir, destination)
                _atomic_write_json(run_dir / "run-record.json", failure)
                session["failures"].append(failure)
                session["execution_order"].append(failure)
                session["status"] = "stopped"
                checkpoint()
                log_event("run_failed", **failure)
                telemetry.stop()
                raise
            finished_utc = _utc_text()
            record = {
                **verified_warmup,
                "run_id": run_id, "kind": "warmup", "round": warmup_index,
                "scenario": scenario.name, "status": "complete", "started_utc": started_utc,
                "finished_utc": finished_utc, "run_directory": str(run_dir), "command": command,
                "process_execution": _executor.metadata,
            }
            telemetry.sample()
            telemetry.set_context(run_id=None, scenario=None, phase="idle")
            retained = _retain_attempt(record, run_dir, destination)
            _atomic_write_json(run_dir / "run-record.json", record)
            if not retained:
                session["failures"].append(record)
            log_event("run_completed" if retained else "run_failed", **record)
            print(
                f"[warmup {warmup_index}/{warmups}] {scenario.name} {record['status']}",
                file=sys.stderr, flush=True,
            )
            execution = {
                **record, "cooldown": {"status": "pending"},
            }
            session["execution_order"].append(execution)
            handled.add(("warmup", warmup_index, scenario.name))
            checkpoint()
            if not retained:
                stop_reason = "retention failure during warmup; partial raw files retained; no further attempts launched"
                execution["cooldown"] = {"status": "not_started_retention_failure", "passed": False}
                checkpoint()
                break
            stop_reason = safety_reason(telemetry.sample())
            if stop_reason is not None:
                execution["cooldown"] = {"status": "not_started_thermal_policy_stop", "passed": False}
                checkpoint()
                break
            execution["cooldown"] = recover()
            print(
                f"[warmup {warmup_index}/{warmups}] cooldown "
                f"{execution['cooldown']['status']} ({execution['cooldown']['elapsed_seconds']:.1f} s)",
                file=sys.stderr, flush=True,
            )
            checkpoint()
            if not execution["cooldown"]["passed"]:
                stop_reason = f"unmet thermal condition after warmup: {execution['cooldown']['status']}"
                break

    scenario_runs = {
        scenario.name: session["scenarios"][scenario.name]["runs"] for scenario in scenarios
    }
    consecutive_failures = 0
    repeat_index = 1
    # Neither validation, initial recovery nor warm-ups consume the measured
    # duration. A resumed measured segment preserves previously committed time.
    active_segment_started = time.monotonic()
    while True:
        if stop_reason is not None:
            break
        active_elapsed = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
        if duration_seconds is None and repeats is not None and repeat_index > repeats:
            break
        if duration_seconds is not None and active_elapsed >= duration_seconds:
            break
        for scenario in ordered("measured", repeat_index):
            if requested_stop():
                stop_reason = "operator graceful stop"
                break
            if already_handled("measured", repeat_index, scenario):
                continue
            active_elapsed = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
            if duration_seconds is not None and active_elapsed >= duration_seconds:
                break
            cycle_started = time.perf_counter()
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
                scenario, run_dir / "products", measurements_path, tle_path, eop_path, plot_path, limit,
                selection_method=selection_method,
                observation_level=observation_level, stage_interval_seconds=stage_interval_seconds,
                native_memory_interval_seconds=native_memory_interval_seconds,
            )
            started_utc = _utc_text()
            from .experiment_control import process_identity
            from .storage import filesystem_capacity
            _atomic_write_json(run_dir / "attempt-intent.json", {
                "run_id": run_id, "kind": "measured", "round": repeat_index,
                "scenario": scenario.name, "started_utc": started_utc, "command": command,
                "supervisor_identity": process_identity(), "policy": "consumes_slot_if_interrupted",
                "capacity_before_attempt": filesystem_capacity(destination),
            })
            telemetry.set_context(
                run_id=run_id, run_directory=run_dir,
                scenario=scenario.name, phase="measured",
            )
            log_event("run_started", run_id=run_id, phase="measured", round=repeat_index, scenario=scenario.name)
            before = system_snapshot()
            operator_interrupted = False
            try:
                outputs, elapsed, _stderr = _executor.run(
                    command, timeout_seconds, child_environment, fresh_runner=child_runner
                )
                run = _validate_run(outputs, elapsed)
                run.update({
                    "run_id": run_id, "status": "complete", "started_utc": started_utc,
                    "finished_utc": _utc_text(), "run_directory": str(run_dir),
                    "system_before": before, "system_after": system_snapshot(),
                    "repeat": repeat_index, "command": command,
                    "stdout_log": str(run_dir / "stdout.log.gz"),
                    "stderr_log": str(run_dir / "stderr.log.gz"),
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
                    "failure_class": failure_classification(exc),
                    "system_before": before, "system_after": system_snapshot(),
                }
                session["failures"].append(record)
            telemetry.sample()
            telemetry.set_context(run_id=None, scenario=None, phase="idle")
            record["process_execution"] = {
                **_executor.metadata,
                "request": _executor.last_request, "response": _executor.last_response,
                "external_timer_scope": "process_launch_to_exit" if process_mode == "fresh" else "persistent_request_roundtrip_with_protocol_persistence",
            }
            if counter_group is not None:
                from .counter_experiment import read_group_result
                raw_counter_path = run_dir / "perf-stat.csv"
                record["hardware_counters"] = read_group_result(raw_counter_path, counter_group, minimum_counter_coverage_percent) if raw_counter_path.exists() else {
                    "status": "not_collected", "reason": counter_capability.get("reason") or "worker failed before perf output",
                    "requested_events": list(counter_group), "capability": counter_capability["status"],
                }
                if raw_counter_path.exists():
                    record["hardware_counters"]["raw_path"] = str(raw_counter_path) + ".gz"
                    record["hardware_counters"]["accounting"]["source_path"] = str(raw_counter_path) + ".gz"
            scientific_complete = record["status"] == "complete"
            retained = _retain_attempt(record, run_dir, destination)
            if not retained and scientific_complete:
                scenario_runs[scenario.name].pop()
                record.update(kind="measured", scenario=scenario.name)
                session["failures"].append(record)
                consecutive_failures += 1
            record["precommit_cycle_seconds"] = time.perf_counter() - cycle_started
            record["cycle_timing_path"] = str(run_dir / "cycle-timing.json")
            record["retained_utc"] = _utc_text()
            _atomic_write_json(run_dir / "run-record.json", record)
            if record["status"] == "complete":
                # Full data lives in the immutable record, not in a growing RAM
                # copy and a repeatedly rewritten monolithic checkpoint.
                scenario_runs[scenario.name][-1] = {
                    "run_id": run_id, "record_path": str(run_dir / "run-record.json")
                }
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
            if record["status"] in ("complete", "failed", "interrupted"):
                handled.add(("measured", repeat_index, scenario.name))
            session["active_elapsed_seconds"] = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
            active_segment_started = time.monotonic()
            log_event(
                "run_completed" if completed else
                ("run_interrupted" if operator_interrupted else "run_failed"),
                **execution,
            )
            checkpoint()
            _commit_cycle_timing(run_dir, run_id, cycle_started)
            if not retained:
                stop_reason = "retention failure during measured attempt; partial raw files retained; no further attempts launched"
                execution["cooldown"] = {"status": "not_started_retention_failure", "passed": False}
                checkpoint()
                break
            stop_reason = safety_reason(telemetry.sample())
            if stop_reason is not None:
                checkpoint()
                break
            if requested_stop():
                stop_reason = "operator graceful stop"
                execution["cooldown"] = {"status": "not_started_operator_stop", "passed": False}
                checkpoint()
                break
            if operator_interrupted:
                stop_reason = "operator interrupt"
                break
            if not completed and (not continue_on_error or consecutive_failures >= max_consecutive_failures):
                stop_reason = (
                    f"run failure; consecutive failures={consecutive_failures}, "
                    f"continue_on_error={continue_on_error}"
                )
                break
            measured_elapsed = float(session.get("active_elapsed_seconds", 0.0)) + time.monotonic() - active_segment_started
            fixed_work_finished = duration_seconds is None and repeat_index == repeats and all(
                ("measured", repeat_index, item.name) in handled for item in scenarios
            )
            if fixed_work_finished or (duration_seconds is not None and measured_elapsed >= duration_seconds):
                execution["cooldown"] = {"status": "not_needed_after_final_attempt", "passed": True}
                checkpoint()
                break
            execution["cooldown"] = recover() if thermal_between_attempts else {
                "status": "continuous_block_no_between_job_recovery", "passed": True, "elapsed_seconds": 0.0,
            }
            print(
                f"[measured {repeat_index}/{repeats or 'duration'}] cooldown "
                f"{execution['cooldown']['status']} ({execution['cooldown']['elapsed_seconds']:.1f} s)",
                file=sys.stderr, flush=True,
            )
            checkpoint()
            if not execution["cooldown"]["passed"]:
                stop_reason = f"unmet thermal condition: {execution['cooldown']['status']}"
                break
        if stop_reason is not None:
            break
        repeat_index += 1

    session["active_elapsed_seconds"] = float(session.get("active_elapsed_seconds", 0.0)) + (time.monotonic() - active_segment_started)
    session["measured_finished_utc"] = _utc_text()
    reporting_started = time.monotonic()
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
        if collect_perf and stop_reason is None:
            print(f"[perf] {scenario.name} starting", file=sys.stderr, flush=True)
            perf_dir = destination / "perf" / scenario.name
            perf_dir.mkdir(parents=True, exist_ok=True)
            perf_command = _analysis_command(
                scenario, perf_dir / "outputs", measurements_path, tle_path, eop_path,
                plot_path, limit, benchmark=False, selection_method=selection_method,
            )
            scenario_report["hardware_counters"] = _perf_run(
                perf_command, perf_dir / "perf-stat.csv", timeout_seconds,
                child_environment,
            )
            print(
                f"[perf] {scenario.name}: {scenario_report['hardware_counters']['status']}",
                file=sys.stderr, flush=True,
            )
        elif collect_perf:
            scenario_report["hardware_counters"] = {
                "status": "not_started", "reason": f"campaign stopped: {stop_reason}",
            }
        checkpoint()

    enough_successful_runs = all(len(runs) >= 1 for runs in scenario_runs.values())
    all_consistent &= enough_successful_runs
    session["scientific_outputs_consistent"] = all_consistent
    session["system_end"] = system_snapshot()
    session["status"] = "complete" if stop_reason is None and all_consistent else "stopped"
    session["stop_reason"] = stop_reason
    measured = [item for item in session["execution_order"] if item.get("kind") == "measured"]
    session["attempt_counts"] = {
        "scheduled": repeats * len(scenarios) if duration_seconds is None else None,
        "started": len(measured),
        "scientifically_valid": sum(item["status"] == "complete" for item in measured),
        "failed": sum(item["status"] == "failed" for item in measured),
        "interrupted": sum(item["status"] == "interrupted" for item in measured),
        "skipped": max(0, repeats * len(scenarios) - len(measured)) if duration_seconds is None else None,
        "automatic_retries": 0,
    }
    session["finished_utc"] = _utc_text()
    session["postmeasurement_seconds"] = time.monotonic() - reporting_started
    telemetry.set_context(run_id=None, scenario=None, phase="finished")
    telemetry.stop()
    _executor.close()
    session["process_segments"][-1].update(_executor.metadata)
    # Give each active segment its own immutable compressed timeline. Resuming
    # opens a new live CSV and never overwrites a previous segment's samples.
    segment_path = telemetry_path.with_name(f"system-telemetry.{telemetry.segment_id}.csv")
    telemetry_path.rename(segment_path)
    compressed_timeline = compress_retained_file(segment_path, remove_original=True)
    session.setdefault("system_telemetry_segments", []).append(_artifact_record(compressed_timeline))
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
