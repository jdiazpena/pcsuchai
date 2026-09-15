"""Stable starting conditions measured with the board's built-in SoC sensor."""

from __future__ import annotations

import math
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Callable

from .benchmark import _temperature_c
from .retention import RawSampleJournal


def _finite(value) -> bool:
    """Require a real finite scalar; booleans/overflow are not sensor values."""

    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def thermal_safety_reason(temperature, maximum_c, require_sensor=False):
    """Evaluate a sampled SoC reading without changing firmware or killing work.

    A configured ceiling requires an available reading. Firmware-protected
    stress uses maximum=None with require_sensor=True; it has no software
    temperature ceiling but cannot silently continue without its sensor.
    """

    if not _finite(temperature):
        return "required SoC temperature reading unavailable or invalid" if require_sensor or maximum_c is not None else None
    if maximum_c is not None and temperature >= maximum_c:
        return f"temperature {temperature} C reached limit {maximum_c} C"
    return None


@dataclass(frozen=True)
class ThermalPolicy:
    """A declared, fail-closed recovery policy; values are protocol parameters.

    Temperature tolerance is relative to this session's measured idle baseline.
    Stability requires a complete window, every reading within tolerance, and
    the absolute least-squares trend below the slope limit. Sensor outages and
    large acquisition gaps cannot pass the gate. No OS/firmware setting changes.
    """

    baseline_seconds: float = 60.0
    stable_seconds: float = 60.0
    tolerance_c: float = 2.0
    maximum_slope_c_per_minute: float = 0.2
    timeout_seconds: float = 600.0
    sample_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Reject impossible or non-finite protocols before any acquisition."""

        for name, value in vars(self).items():
            if not _finite(value) or value <= 0:
                raise ValueError(f"thermal {name} must be finite and positive")
        if self.timeout_seconds < self.stable_seconds:
            raise ValueError("thermal timeout must cover the stability window")
        if self.sample_interval_seconds > min(self.stable_seconds, self.baseline_seconds) / 2:
            raise ValueError("thermal interval must allow at least three window readings")


def temperature_slope(samples: list[tuple[float, float]]) -> float | None:
    """Fit degrees Celsius/minute against monotonic seconds, not UTC time."""

    if len(samples) < 2:
        return None
    origin = samples[0][0]
    xs = [t - origin for t, _ in samples]
    xmean = math.fsum(xs) / len(xs)
    ymean = math.fsum(value for _, value in samples) / len(samples)
    denominator = math.fsum((x - xmean) ** 2 for x in xs)
    if denominator <= 0:
        return None
    return 60.0 * math.fsum((x - xmean) * (value - ymean) for x, (_, value) in zip(xs, samples)) / denominator


def acquire_thermal_condition(
    policy: ThermalPolicy,
    trace_path: Path,
    *,
    baseline_c: float | None = None,
    sensor: Callable[[], float | None] = _temperature_c,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Measure an idle baseline or wait for stable recovery, retaining all rows.

    Without a baseline, acquire the declared idle interval and return its median.
    With a baseline, wait until the complete trailing stability window passes.
    The caller must end/pause measured work unless ``passed`` is true. The raw
    trace is losslessly compressed even when the sensor or gate fails.
    Clock/sensor injection supports deterministic replay of real or test traces.
    """

    if baseline_c is not None and not _finite(baseline_c):
        raise ValueError("idle baseline must be finite")
    from .campaign_costs import cost_clock
    from .benchmark import sha256_file
    cost_started = cost_clock()
    is_baseline = baseline_c is None
    window_seconds = policy.baseline_seconds if is_baseline else policy.stable_seconds
    deadline = policy.baseline_seconds if is_baseline else policy.timeout_seconds
    samples: deque[tuple[float, float]] = deque()
    journal = RawSampleJournal(trace_path, (
        "captured_utc", "elapsed_seconds", "monotonic_seconds", "temperature_c",
        "baseline_c", "slope_c_per_minute", "window_span_seconds", "status",
        "clock_error", "raw_clock_repr",
    ))
    started = clock()
    count = 0
    status = "acquiring"
    slope = None
    final_temperature = None
    acquired_baseline = baseline_c
    previous_clock = started
    elapsed = None
    try:
        while True:
            now = clock()
            if (not _finite(started) or started < 0 or not _finite(now)
                    or now < 0 or now < previous_clock):
                status = "clock_invalid"
                elapsed = None
                journal.append({"captured_utc": datetime.now(timezone.utc).isoformat(),
                                "baseline_c": baseline_c, "status": status,
                                "clock_error": "non-finite, invalid or regressing monotonic protocol clock",
                                "raw_clock_repr": repr((started, now, previous_clock))})
                break
            previous_clock = now
            elapsed = now - started
            if cancelled is not None and cancelled():
                status = "cancelled"
                journal.append({"captured_utc": datetime.now(timezone.utc).isoformat(),
                                "elapsed_seconds": elapsed, "monotonic_seconds": now,
                                "baseline_c": baseline_c, "status": status})
                break
            temperature = sensor()
            count += 1
            available = _finite(temperature)
            final_temperature = temperature if available else None
            if available:
                samples.append((now, float(temperature)))
                # Retain one predecessor to cover the full window; memory is
                # bounded by the protocol's fixed interval/window, not runtime.
                while len(samples) > 2 and samples[1][0] <= now - window_seconds:
                    samples.popleft()
                slope = temperature_slope(list(samples))
            span = samples[-1][0] - samples[0][0] if samples else 0.0
            gaps_valid = all(b[0] - a[0] <= policy.sample_interval_seconds * 1.5 for a, b in zip(samples, list(samples)[1:]))
            if not available:
                status = "sensor_unavailable"
            elif is_baseline and elapsed >= policy.baseline_seconds and gaps_valid:
                acquired_baseline = median(value for _, value in samples)
                status = "baseline_acquired"
            elif not is_baseline and span >= window_seconds and gaps_valid and slope is not None:
                if all(abs(value - baseline_c) <= policy.tolerance_c for _, value in samples) and abs(slope) <= policy.maximum_slope_c_per_minute:
                    status = "stable"
            if status == "acquiring" and elapsed >= deadline:
                status = "maximum_wait_reached"
            journal.append({
                "captured_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": elapsed, "monotonic_seconds": now,
                "temperature_c": final_temperature, "baseline_c": baseline_c,
                "slope_c_per_minute": slope, "window_span_seconds": span,
                "status": status,
            })
            if status != "acquiring":
                break
            sleep(min(policy.sample_interval_seconds, max(0.0, deadline - elapsed)))
    finally:
        retained_trace = journal.finish()
    trace = Path(retained_trace)
    trace_hash = sha256_file(trace)
    cost_ended = cost_clock()
    acquisition_cost = {"schema_version": 1, "started": cost_started, "ended": cost_ended,
                        "wall_seconds": cost_ended["monotonic_seconds"] - cost_started["monotonic_seconds"],
                        "parent_process_cpu_seconds": cost_ended["process_cpu_seconds"] - cost_started["process_cpu_seconds"],
                        "scope": "thermal_acquisition_call_including_journal_compression_and_trace_hash",
                        "source": "time.monotonic/time.process_time", "units": "seconds",
                        "trace_name": trace.name, "trace_sha256": trace_hash,
                        "result_status": status, "passed": status in ("baseline_acquired", "stable"),
                        "limit": "contained in block/API elapsed time; excludes own receipt write and caller checkpoints; injected protocol clocks remain separate from actual call cost"}
    receipt = trace.with_name(trace.name + ".receipt.json")
    with receipt.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(acquisition_cost, indent=2, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "passed": status in ("baseline_acquired", "stable"),
        "status": status, "baseline_c": acquired_baseline,
        "final_temperature_c": final_temperature,
        "final_slope_c_per_minute": slope,
        "elapsed_seconds": elapsed, "sample_count": count,
        "trace_path": str(retained_trace) if retained_trace else None, "policy": vars(policy),
        "source": "/sys/class/thermal/thermal_zone0/temp", "scope": "board_soc",
        "acquisition_cost": acquisition_cost, "cost_receipt": str(receipt),
    }
