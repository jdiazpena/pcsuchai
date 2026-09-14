"""Opt-in, stage-consistent performance measurements."""

from __future__ import annotations

import json
import hashlib
import os
import platform
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from datetime import datetime, timezone


def runtime_metadata() -> dict:
    """Describe the interpreter, platform, and scientific package versions."""

    from importlib.metadata import PackageNotFoundError, version

    packages = {}
    for name in (
        "pcsuchai", "numpy", "matplotlib", "astropy", "sgp4", "skyfield",
        "aacgmv2", "apexpy", "psutil",
    ):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    if packages["pcsuchai"] is None:
        from . import __version__

        packages["pcsuchai"] = __version__
    cpu_model = None
    cpu_candidates = {}
    try:
        for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
            if ":" in line:
                key, value = (item.strip() for item in line.split(":", 1))
                if key.lower() in ("model name", "hardware", "model") and value:
                    cpu_candidates.setdefault(key.lower(), value)
    except (FileNotFoundError, PermissionError):
        pass
    cpu_model = cpu_candidates.get("model name") or cpu_candidates.get("hardware")
    if cpu_model is None and not cpu_candidates.get("model", "").isdigit():
        cpu_model = cpu_candidates.get("model")
    board_model = None
    try:
        board_model = Path("/proc/device-tree/model").read_bytes().replace(b"\0", b"").decode().strip() or None
    except (FileNotFoundError, PermissionError, UnicodeDecodeError):
        pass
    return {
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "cpu_model": cpu_model,
        "board_model": board_model,
        "cpu_governor": _cpu_governor(),
        "packages": packages,
    }


def sha256_file(path: str | Path) -> str:
    """Calculate a file digest without loading the entire artifact in memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cpu_governor() -> str | None:
    """Return CPU0's Linux scaling governor when exposed by the kernel."""

    try:
        return Path(
            "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        ).read_text().strip() or None
    except (FileNotFoundError, PermissionError):
        return None


def _process_faults() -> tuple[int | None, int | None]:
    """Read this process's Linux minor and major page-fault counters."""

    try:
        fields = Path("/proc/self/stat").read_text().split()
        return int(fields[9]), int(fields[11])
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        return None, None


def _temperature_c() -> float | None:
    """Read the primary Linux thermal zone without invoking external tools."""

    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
    except (FileNotFoundError, PermissionError, ValueError):
        return None


def system_snapshot(path: str | Path | None = None) -> dict:
    """Capture non-identifying host state at a benchmark boundary."""

    snapshot = {
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "temperature_c": _temperature_c(),
        "throttled": _throttled(),
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "runtime": runtime_metadata(),
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
            "logical_cpu_percent": psutil.cpu_percent(interval=0.1, percpu=True),
            "process_count": len(psutil.pids()),
            "uptime_seconds": float(time.time() - psutil.boot_time()),
        })
    except (ImportError, OSError):
        snapshot["psutil_metrics"] = "unavailable"
    if path is not None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def _throttled() -> str | None:
    """Return Raspberry Pi firmware throttling flags when available."""

    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip().removeprefix("throttled=") or None


@dataclass(frozen=True)
class StageMetrics:
    """Common performance fields recorded for every measured stage."""

    stage: str
    started_utc: str
    finished_utc: str
    wall_seconds: float
    process_cpu_seconds: float
    process_user_seconds: float
    process_system_seconds: float
    cpu_equivalent_percent: float
    peak_rss_bytes: int
    rss_change_bytes: int
    read_bytes: int | None
    write_bytes: int | None
    read_chars: int | None
    write_chars: int | None
    voluntary_context_switches: int | None
    involuntary_context_switches: int | None
    minor_page_faults: int | None
    major_page_faults: int | None
    peak_threads: int
    available_memory_start_bytes: int
    available_memory_min_bytes: int
    available_memory_end_bytes: int
    load_average_start: tuple[float, float, float] | None
    load_average_end: tuple[float, float, float] | None
    temperature_start_c: float | None
    temperature_max_c: float | None
    temperature_end_c: float | None
    cpu_frequency_min_mhz: float | None
    cpu_frequency_max_mhz: float | None
    throttled_start: str | None
    throttled_end: str | None


class BenchmarkRecorder:
    """Collect low-overhead process and system samples when explicitly enabled."""

    def __init__(
        self, enabled: bool, sample_interval: float = 0.05,
        *, sample_path: str | Path | None = None,
    ) -> None:
        """Configure summaries plus a mandatory on-disk raw journal when enabled."""

        self.enabled = enabled
        self.sample_interval = sample_interval
        self.results: list[StageMetrics] = []
        self.raw_sample_path: Path | None = None
        self.journal = None
        if enabled:
            if sample_path is None:
                raise ValueError("enabled benchmarking requires a raw sample_path")
            if sample_interval <= 0:
                raise ValueError("sample_interval must be positive")
            from .retention import RawSampleJournal

            self.journal = RawSampleJournal(Path(sample_path), (
                "captured_utc", "stage", "phase", "stage_elapsed_seconds",
                "monotonic_seconds", "process_cpu_seconds",
                "sample_interval_seconds", "rss_bytes", "threads",
                "available_memory_bytes", "used_memory_bytes", "swap_used_bytes",
                "temperature_c", "cpu_frequency_mhz", "load_1m",
                "process_user_seconds", "process_system_seconds", "read_bytes",
                "write_bytes", "read_chars", "write_chars", "voluntary_context_switches",
                "involuntary_context_switches", "minor_page_faults", "major_page_faults",
                "throttled", "sample_error",
            ))

    @contextmanager
    def measure(self, stage: str):
        """Measure one pipeline stage using the same metric schema as all others."""

        if not self.enabled:
            yield
            return
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("benchmarking requires psutil") from exc

        process = psutil.Process()
        rss_start = process.memory_info().rss
        io_start = process.io_counters() if hasattr(process, "io_counters") else None
        cpu_times_start = process.cpu_times()
        context_start = process.num_ctx_switches()
        faults_start = _process_faults()
        available_start = int(psutil.virtual_memory().available)
        load_start = tuple(float(item) for item in os.getloadavg()) if hasattr(os, "getloadavg") else None
        temp_start = _temperature_c()
        started_utc = datetime.now(timezone.utc).isoformat()
        throttle_start = _throttled()
        samples_rss = [rss_start]
        samples_temp = [temp_start] if temp_start is not None else []
        samples_freq: list[float] = []
        samples_threads = [process.num_threads()]
        samples_available = [available_start]
        stop = threading.Event()
        sampling_errors: list[Exception] = []
        sample_started = time.perf_counter()

        def capture(phase: str, throttled: str | None = None) -> None:
            """Save every acquired value with UTC and monotonic time, not just extrema."""

            row = {
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "stage": stage, "phase": phase,
                "stage_elapsed_seconds": time.perf_counter() - sample_started,
                "monotonic_seconds": time.perf_counter(),
                "process_cpu_seconds": time.process_time(),
                "sample_interval_seconds": self.sample_interval, "throttled": throttled,
            }
            try:
                rss = process.memory_info().rss
                threads = process.num_threads()
                memory = psutil.virtual_memory()
                swap = psutil.swap_memory()
                current_temp = _temperature_c()
                frequency = psutil.cpu_freq()
                cpu_times = process.cpu_times()
                io = process.io_counters() if hasattr(process, "io_counters") else None
                context = process.num_ctx_switches()
                faults = _process_faults()
                row.update({
                    "rss_bytes": rss, "threads": threads,
                    "available_memory_bytes": int(memory.available),
                    "used_memory_bytes": int(memory.used), "swap_used_bytes": int(swap.used),
                    "temperature_c": current_temp,
                    "cpu_frequency_mhz": float(frequency.current) if frequency else None,
                    "load_1m": os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
                    "process_user_seconds": cpu_times.user,
                    "process_system_seconds": cpu_times.system,
                    "read_bytes": io.read_bytes if io else None,
                    "write_bytes": io.write_bytes if io else None,
                    "read_chars": getattr(io, "read_chars", None),
                    "write_chars": getattr(io, "write_chars", None),
                    "voluntary_context_switches": context.voluntary,
                    "involuntary_context_switches": context.involuntary,
                    "minor_page_faults": faults[0], "major_page_faults": faults[1],
                })
                samples_rss.append(rss)
                samples_threads.append(threads)
                samples_available.append(int(memory.available))
                if current_temp is not None:
                    samples_temp.append(current_temp)
                if frequency is not None:
                    samples_freq.append(float(frequency.current))
            except (psutil.Error, OSError) as exc:
                row["sample_error"] = f"{type(exc).__name__}: {exc}"
            # Persistence errors deliberately escape: silently losing raw data is invalid.
            self.journal.append(row)

        def sample() -> None:
            while not stop.wait(self.sample_interval):
                try:
                    capture("sample")
                except Exception as exc:
                    sampling_errors.append(exc)
                    stop.set()
                    break

        sampler = threading.Thread(target=sample, daemon=True)
        capture("start", throttle_start)
        cpu_start = time.process_time()
        wall_start = time.perf_counter()
        sampler.start()
        try:
            yield
        finally:
            wall = time.perf_counter() - wall_start
            cpu = time.process_time() - cpu_start
            stop.set()
            sampler.join()
            rss_end = process.memory_info().rss
            samples_rss.append(rss_end)
            io_end = process.io_counters() if hasattr(process, "io_counters") else None
            cpu_times_end = process.cpu_times()
            context_end = process.num_ctx_switches()
            faults_end = _process_faults()
            available_end = int(psutil.virtual_memory().available)
            samples_available.append(available_end)
            temp_end = _temperature_c()
            finished_utc = datetime.now(timezone.utc).isoformat()
            if temp_end is not None:
                samples_temp.append(temp_end)
            throttle_end = _throttled()
            capture("end", throttle_end)
            self.journal.sync()
            if sampling_errors:
                raise RuntimeError("raw stage sample persistence failed") from sampling_errors[0]
            self.results.append(
                StageMetrics(
                    stage=stage,
                    started_utc=started_utc,
                    finished_utc=finished_utc,
                    wall_seconds=wall,
                    process_cpu_seconds=cpu,
                    process_user_seconds=float(cpu_times_end.user - cpu_times_start.user),
                    process_system_seconds=float(cpu_times_end.system - cpu_times_start.system),
                    cpu_equivalent_percent=100.0 * cpu / wall if wall else 0.0,
                    peak_rss_bytes=max(samples_rss),
                    rss_change_bytes=rss_end - rss_start,
                    read_bytes=(io_end.read_bytes - io_start.read_bytes) if io_start and io_end else None,
                    write_bytes=(io_end.write_bytes - io_start.write_bytes) if io_start and io_end else None,
                    read_chars=(
                        getattr(io_end, "read_chars", 0) - getattr(io_start, "read_chars", 0)
                        if io_start and io_end and hasattr(io_end, "read_chars") else None
                    ),
                    write_chars=(
                        getattr(io_end, "write_chars", 0) - getattr(io_start, "write_chars", 0)
                        if io_start and io_end and hasattr(io_end, "write_chars") else None
                    ),
                    voluntary_context_switches=(
                        context_end.voluntary - context_start.voluntary
                    ),
                    involuntary_context_switches=(
                        context_end.involuntary - context_start.involuntary
                    ),
                    minor_page_faults=(
                        faults_end[0] - faults_start[0]
                        if faults_start[0] is not None and faults_end[0] is not None else None
                    ),
                    major_page_faults=(
                        faults_end[1] - faults_start[1]
                        if faults_start[1] is not None and faults_end[1] is not None else None
                    ),
                    peak_threads=max(samples_threads),
                    available_memory_start_bytes=available_start,
                    available_memory_min_bytes=min(samples_available),
                    available_memory_end_bytes=available_end,
                    load_average_start=load_start,
                    load_average_end=(
                        tuple(float(item) for item in os.getloadavg())
                        if hasattr(os, "getloadavg") else None
                    ),
                    temperature_start_c=temp_start,
                    temperature_max_c=max(samples_temp) if samples_temp else None,
                    temperature_end_c=temp_end,
                    cpu_frequency_min_mhz=min(samples_freq) if samples_freq else None,
                    cpu_frequency_max_mhz=max(samples_freq) if samples_freq else None,
                    throttled_start=throttle_start,
                    throttled_end=throttle_end,
                )
            )

    def write_json(self, path: str | Path) -> None:
        """Write summaries and losslessly compress every raw monitoring sample."""

        Path(path).write_text(json.dumps([asdict(item) for item in self.results], indent=2) + "\n")
        if self.journal is not None:
            self.raw_sample_path = self.journal.finish()
