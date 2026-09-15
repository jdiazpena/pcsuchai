"""Timestamped software measurements with explicit source, scope and availability."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def measurement(value, *, unit: str, scope: str, source: str,
                status: str | None = None, reason: str | None = None) -> dict:
    """Wrap a reading without conflating zero, missing, denied or unsupported.

    Acquisition times belong to the individual reading. Summary times do not
    replace them. Structured values retain their raw components and units.
    """

    return {
        "value": value, "unit": unit, "scope": scope, "source": source,
        "status": status or ("available" if value is not None else "unavailable"),
        "reason": reason, "captured_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_seconds": time.monotonic(),
    }


def _error_status(exc: Exception) -> str:
    """Preserve permission failures separately from absent OS capabilities."""

    if isinstance(exc, PermissionError) or type(exc).__name__ == "AccessDenied":
        return "denied"
    if isinstance(exc, FileNotFoundError):
        return "unsupported"
    if type(exc).__name__ in ("NoSuchProcess", "ZombieProcess"):
        return "process_exited"
    return "unavailable"


def _read_value(path: Path, convert, unit: str, scope: str) -> dict:
    """Read one kernel field and retain a classified acquisition failure."""

    try:
        return measurement(convert(path.read_text().strip()), unit=unit, scope=scope, source=str(path))
    except (OSError, ValueError) as exc:
        return measurement(None, unit=unit, scope=scope, source=str(path),
                           status=_error_status(exc), reason=f"{type(exc).__name__}: {exc}")


def read_pressure(path: Path) -> dict:
    """Read Linux PSI averages (%) and cumulative stall time (microseconds)."""

    def parse(text):
        result = {}
        for line in text.splitlines():
            parts = line.split()
            fields = dict(part.split("=", 1) for part in parts[1:])
            if parts[0] not in ("some", "full"):
                raise ValueError("unknown PSI category")
            result[parts[0]] = {
                "avg10_percent": float(fields["avg10"]),
                "avg60_percent": float(fields["avg60"]),
                "avg300_percent": float(fields["avg300"]),
                "total_microseconds": int(fields["total"]),
            }
        if not result:
            raise ValueError("empty PSI record")
        return result

    try:
        return _read_value(path, parse, "structured_percent_and_microseconds", "board")
    except (KeyError, IndexError) as exc:
        return measurement(None, unit="structured_percent_and_microseconds", scope="board",
                           source=str(path), reason=f"malformed PSI: {exc}")


def read_process_high_water(pid: int, proc_root: Path = Path("/proc"), *, scope: str = "worker") -> dict:
    """Read kernel VmHWM bytes; this is a process-lifetime peak, not a stage peak."""

    path = proc_root / str(pid) / "status"
    try:
        fields = {}
        for line in path.read_text().splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key] = value.strip()
        value, unit = fields["VmHWM"].split()
        if unit != "kB":
            raise ValueError("unexpected VmHWM unit")
        return measurement(int(value) * 1024, unit="bytes", scope=scope, source=f"{path}:VmHWM")
    except KeyError:
        return measurement(None, unit="bytes", scope=scope, source=f"{path}:VmHWM",
                           status="unsupported", reason="kernel did not expose VmHWM")
    except (OSError, ValueError) as exc:
        return measurement(None, unit="bytes", scope=scope, source=f"{path}:VmHWM",
                           status=_error_status(exc), reason=f"{type(exc).__name__}: {exc}")


def process_measurements(pid: int, *, scope: str, native_memory: bool = False) -> dict:
    """Capture one process's cumulative counters and live resource state.

    PSS/USS acquisition is requested at a lower cadence by the owning sampler.
    It reads native/kernel memory accounting, not Python allocation estimates.
    Unsupported fields remain present with status; process exits are retained.
    """

    fields = {
        "rss_bytes": ("bytes", "memory_info", "rss"),
        "cpu_user_seconds": ("seconds", "cpu_times", "user"),
        "cpu_system_seconds": ("seconds", "cpu_times", "system"),
        "threads": ("count", "num_threads", None),
        "file_descriptors": ("count", "num_fds", None),
        "cpu_number": ("index", "cpu_num", None),
        "read_bytes": ("bytes", "io_counters", "read_bytes"),
        "write_bytes": ("bytes", "io_counters", "write_bytes"),
        "read_chars": ("bytes", "io_counters", "read_chars"),
        "write_chars": ("bytes", "io_counters", "write_chars"),
        "voluntary_context_switches": ("count", "num_ctx_switches", "voluntary"),
        "involuntary_context_switches": ("count", "num_ctx_switches", "involuntary"),
        "pss_bytes": ("bytes", "memory_full_info", "pss"),
        "uss_bytes": ("bytes", "memory_full_info", "uss"),
    }
    results = {}
    calls = {}
    try:
        import psutil
        process = psutil.Process(pid)
    except (ImportError, OSError) as exc:
        process = None
        unavailable = exc
    except Exception as exc:
        # psutil.NoSuchProcess is not an OSError.
        process = None
        unavailable = exc
    for name, (unit, method, attribute) in fields.items():
        source = f"psutil.Process({pid}).{method}"
        if method == "memory_full_info" and not native_memory:
            results[name] = measurement(None, unit=unit, scope=scope, source=source,
                                        status="not_sampled", reason="lower-rate native-memory acquisition")
            continue
        try:
            if process is None:
                raise unavailable
            if method not in calls:
                try:
                    calls[method] = getattr(process, method)()
                except Exception as exc:
                    calls[method] = exc
            item = calls[method]
            if isinstance(item, Exception):
                raise item
            value = getattr(item, attribute) if attribute else item
            results[name] = measurement(value, unit=unit, scope=scope, source=source)
        except AttributeError as exc:
            results[name] = measurement(None, unit=unit, scope=scope, source=source,
                                        status="unsupported", reason=str(exc))
        except Exception as exc:
            results[name] = measurement(None, unit=unit, scope=scope, source=source,
                                        status=_error_status(exc), reason=f"{type(exc).__name__}: {exc}")
    results["lifetime_high_water_rss_bytes"] = read_process_high_water(pid, scope=scope)
    return results


def firmware_arm_clock() -> dict:
    """Read observed Arm clock from Raspberry Pi firmware, separately from CPUFreq."""

    source = "vcgencmd measure_clock arm"
    try:
        completed = subprocess.run(["vcgencmd", "measure_clock", "arm"],
                                   capture_output=True, text=True, timeout=2, check=False)
        if completed.returncode:
            return measurement(None, unit="Hz", scope="board", source=source,
                               reason=f"exit {completed.returncode}: {completed.stderr.strip()}")
        key, separator, raw = completed.stdout.strip().partition("=")
        if not separator or not key.startswith("frequency("):
            raise ValueError("unexpected firmware clock response")
        return measurement(int(raw), unit="Hz", scope="board", source=source)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return measurement(None, unit="Hz", scope="board", source=source,
                           status=_error_status(exc), reason=f"{type(exc).__name__}: {exc}")


def firmware_throttling() -> dict:
    """Acquire the firmware mask once, retaining status and actual timestamps."""

    from .firmware import parse_throttling_mask
    source = "vcgencmd get_throttled"
    try:
        completed = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                                   text=True, timeout=2, check=False)
        if completed.returncode:
            return measurement(None, unit="firmware_bitmask", scope="board", source=source,
                               reason=f"exit {completed.returncode}: {completed.stderr.strip()}")
        key, separator, raw = completed.stdout.strip().partition("=")
        if key != "throttled" or not separator:
            raise ValueError("unexpected firmware throttling response")
        return measurement(parse_throttling_mask(raw), unit="firmware_bitmask", scope="board", source=source)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return measurement(None, unit="firmware_bitmask", scope="board", source=source,
                           status=_error_status(exc), reason=f"{type(exc).__name__}: {exc}")


def process_details(pid: int, *, scope: str) -> dict:
    """Acquire explicitly heavy thread/affinity/memory-map detail at low rate.

    Native map quantities retain their named byte fields; thread CPU quantities
    are seconds. This snapshot is detailed instrumentation, not simultaneous
    hardware profiling or a claim that every scheduler migration was sampled.
    """

    specifications = {
        "threads": ("threads", "structured_thread_ids_and_cpu_seconds", lambda rows: [row._asdict() for row in rows]),
        "affinity": ("cpu_affinity", "cpu_indices", list),
        "memory_maps": ("memory_maps", "structured_map_paths_and_bytes", lambda rows: [row._asdict() for row in rows]),
    }
    result = {}
    for name, (method, unit, transform) in specifications.items():
        try:
            import psutil
            value = transform(getattr(psutil.Process(pid), method)())
            result[name] = measurement(value, unit=unit, scope=scope, source=f"psutil.Process({pid}).{method}")
        except Exception as exc:
            result[name] = measurement(None, unit=unit, scope=scope, source=f"psutil.Process({pid}).{method}",
                                       status=_error_status(exc), reason=f"{type(exc).__name__}: {exc}")
    return result


class ObservationSampler:
    """Acquire supervisor/board resources with lower-rate expensive observations.

    The sampler stores at most the previous CPU totals and one acquisition time.
    Every returned reading is persisted by the caller's append-only journal.
    No missing value is filled from a previous sample. CPU percentages derive
    from changes in actual process CPU seconds over monotonic acquisition time.
    """

    def __init__(self, native_interval_seconds: float = 10.0) -> None:
        """Declare expensive acquisition cadence independently of board sampling."""

        if not math.isfinite(native_interval_seconds) or native_interval_seconds <= 0:
            raise ValueError("native-memory interval must be finite and positive")
        self.native_interval_seconds = native_interval_seconds
        self.last_native = None
        self.previous_cpu: dict[str, tuple[int, float, float]] = {}
        self.previous_core_ticks = None

    def capture(self, storage_path: Path, *, worker_pid: int | None = None) -> dict:
        """Return a complete capability-labelled reading set for this acquisition."""

        now = time.monotonic()
        detailed = self.last_native is None or now - self.last_native >= self.native_interval_seconds
        if detailed:
            self.last_native = now
        result = {"schema_version": 1, "board": {}, "supervisor": {}, "worker": {}}
        for scope, pid in (("supervisor", os.getpid()), ("worker", worker_pid)):
            if pid is None:
                continue
            values = process_measurements(pid, scope=scope, native_memory=detailed)
            user, system = values["cpu_user_seconds"]["value"], values["cpu_system_seconds"]["value"]
            percent = None
            status = "initializing"
            if user is not None and system is not None:
                total = user + system
                acquired = values["cpu_system_seconds"]["monotonic_seconds"]
                previous = self.previous_cpu.get(scope)
                if previous is not None and pid == previous[0] and acquired > previous[1] and total >= previous[2]:
                    percent = 100 * (total - previous[2]) / (acquired - previous[1])
                    status = "available"
                self.previous_cpu[scope] = (pid, acquired, total)
            else:
                status = "unavailable"
            values["cpu_equivalent_percent"] = measurement(percent, unit="percent_of_one_cpu", scope=scope,
                                                            source="process_cpu_delta/monotonic_delta", status=status)
            result[scope] = values
        board = result["board"]
        board["soc_temperature_c"] = _read_value(Path("/sys/class/thermal/thermal_zone0/temp"),
                                                lambda text: int(text) / 1000, "degrees_Celsius", "board_soc")
        board["requested_frequency_hz"] = _read_value(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
                                                     lambda text: int(text) * 1000, "Hz", "board_cpu0")
        board["observed_firmware_arm_frequency_hz"] = firmware_arm_clock() if detailed else measurement(
            None, unit="Hz", scope="board", source="vcgencmd measure_clock arm",
            status="not_sampled", reason="lower-rate firmware acquisition")
        for resource in ("cpu", "memory", "io"):
            board[f"{resource}_pressure"] = read_pressure(Path("/proc/pressure") / resource)
        try:
            cores = {}
            for line in Path("/proc/stat").read_text().splitlines():
                parts = line.split()
                if parts and parts[0].startswith("cpu") and parts[0][3:].isdigit():
                    cores[parts[0]] = [int(value) for value in parts[1:9]]
            if not cores:
                raise ValueError("no per-core CPU accounting")
            board["per_core_cpu_ticks"] = measurement(cores, unit="kernel_clock_ticks", scope="board_per_core", source="/proc/stat")
            percentages = {}
            if self.previous_core_ticks is not None and self.previous_core_ticks.keys() == cores.keys():
                for core, ticks in cores.items():
                    previous = self.previous_core_ticks[core]
                    deltas = [value - before for value, before in zip(ticks, previous)]
                    total = sum(deltas)
                    # Linux user/nice already include guest; fields beyond the
                    # first eight must not be double-counted in total CPU time.
                    percentages[core] = 100 * (total - deltas[3] - deltas[4]) / total if total > 0 and min(deltas) >= 0 else None
            self.previous_core_ticks = cores
            board["per_core_utilization_percent"] = measurement(
                percentages or None, unit="percent", scope="board_per_core", source="/proc/stat deltas (idle and iowait excluded)",
                status="available" if percentages else "initializing")
        except (OSError, ValueError, IndexError) as exc:
            for name, unit in (("per_core_cpu_ticks", "kernel_clock_ticks"), ("per_core_utilization_percent", "percent")):
                board[name] = measurement(None, unit=unit, scope="board_per_core", source="/proc/stat",
                                          status=_error_status(exc), reason=str(exc))
        try:
            import psutil
            memory, swap = psutil.virtual_memory(), psutil.swap_memory()
            board["ram"] = measurement(memory._asdict(), unit="structured_bytes_and_percent", scope="board", source="psutil.virtual_memory")
            board["swap"] = measurement(swap._asdict(), unit="structured_bytes_and_percent", scope="board", source="psutil.swap_memory")
        except (ImportError, OSError) as exc:
            for name in ("ram", "swap"):
                board[name] = measurement(None, unit="structured_bytes_and_percent", scope="board", source=f"psutil.{name}", reason=str(exc))
        try:
            filesystem = os.statvfs(storage_path)
            for name, value, unit in (
                ("free_bytes", filesystem.f_bavail * filesystem.f_frsize, "bytes"),
                ("free_inodes", filesystem.f_favail, "count"),
                ("block_size_bytes", filesystem.f_frsize, "bytes"),
            ):
                board[name] = measurement(value, unit=unit, scope="storage_filesystem", source="os.statvfs")
        except OSError as exc:
            for name, unit in (("free_bytes", "bytes"), ("free_inodes", "count"), ("block_size_bytes", "bytes")):
                board[name] = measurement(None, unit=unit, scope="storage_filesystem", source="os.statvfs",
                                          status=_error_status(exc), reason=str(exc))
        return result

    def capture_json(self, storage_path: Path, *, worker_pid: int | None = None) -> str:
        """Encode readings for one raw CSV cell without altering numeric precision."""

        return json.dumps(self.capture(storage_path, worker_pid=worker_pid), separators=(",", ":"), allow_nan=False)
