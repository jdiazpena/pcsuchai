"""Saved SoC temperature windows and firmware transitions, without extra sensors."""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass

from .firmware import CURRENT_FLAGS, KNOWN_FLAG_MASK, decode_throttling_mask
from .reading_statistics import ReadingTrend


@dataclass(frozen=True)
class ThermalAnalysisPolicy:
    """Exploratory report criteria, not a calibrated hardware protection policy.

    Windows close on actual acquisition span, sharing one boundary reading.
    Consecutive qualifying windows provide candidate plateau evidence only;
    the report never infers causal temperature dependence or physical equilibrium.
    """

    window_seconds: float = 300.0
    maximum_slope_c_per_minute: float = 0.2
    maximum_range_c: float = 2.0
    maximum_gap_factor: float = 1.5
    consecutive_windows: int = 2

    def __post_init__(self):
        """Reject bool/non-finite/non-positive settings before reading journals."""

        for name in ("window_seconds", "maximum_slope_c_per_minute", "maximum_range_c", "maximum_gap_factor"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"thermal analysis {name} must be finite and positive")
        if type(self.consecutive_windows) is not int or self.consecutive_windows < 2:
            raise ValueError("thermal analysis requires at least two consecutive windows")


def _numeric_reading(reading: dict) -> bool:
    """Require available finite non-boolean value AND original monotonic time."""

    return reading.get("status") == "available" and all(
        type(reading.get(key)) in (int, float) and math.isfinite(reading[key])
        for key in ("value", "monotonic_seconds"))


class TemperatureWindows:
    """Constant-memory observed-span windows, phase summaries and gap accounting."""

    def __init__(self, policy: ThermalAnalysisPolicy, interval_seconds: float):
        """Use the frozen requested cadence only as a declared gap criterion."""

        if type(interval_seconds) not in (int, float) or not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("temperature interval must be finite and positive")
        self.policy, self.maximum_gap = policy, interval_seconds * policy.maximum_gap_factor
        self.total, self.window = ReadingTrend(), ReadingTrend()
        self.phases = {}
        self.started_measured = False
        self.last_included = None
        self.window_count = self.qualifying_count = self.consecutive = self.longest_consecutive = 0
        self.interruptions = Counter()

    def _close(self, reason: str) -> dict | None:
        """Emit every partial/nonqualifying window; keep no timeline in RAM."""

        if not self.window.count:
            return None
        detail = self.window.report()
        slope = detail["linear_slope_per_second"]
        slope = slope * 60 if slope is not None else None
        span = detail["observed_span_seconds"]
        delta = detail["maximum"] - detail["minimum"]
        qualified = (reason == "observed_window_complete" and self.window.count >= 3
                     and span >= self.policy.window_seconds and slope is not None
                     and abs(slope) <= self.policy.maximum_slope_c_per_minute
                     and delta <= self.policy.maximum_range_c)
        self.window_count += 1
        self.qualifying_count += qualified
        self.consecutive = self.consecutive + 1 if qualified else 0
        self.longest_consecutive = max(self.longest_consecutive, self.consecutive)
        self.window = ReadingTrend()
        return {"window_number": self.window_count, "reason": reason,
                "qualifies_low_slope_small_range": bool(qualified), "slope_c_per_minute": slope,
                "temperature_range_c": delta, "samples": detail,
                "boundary_reading_shared_with_next_complete_window": reason == "observed_window_complete"}

    def add(self, reading: dict, phase: str) -> list[dict]:
        """Separate premeasurement phases; gaps/outages break consecutive evidence.

        Retention/idle between continuous jobs is part of the sustained block,
        not a fictitious cooldown. Phase labels are saved sampler contexts,
        not atomic timestamps of every independent reading's stage boundary.
        """

        self.total.add(reading)
        self.phases.setdefault(phase, ReadingTrend()).add(reading)
        if phase == "measured":
            self.started_measured = True
        if not self.started_measured:
            return []
        results = []
        reason = None
        if phase not in ("measured", "idle"):
            reason = "noncontinuous_phase"
        elif not _numeric_reading(reading):
            reason = "unavailable_or_malformed_reading"
        elif self.last_included is not None:
            gap = reading["monotonic_seconds"] - self.last_included
            if gap <= 0:
                reason = "duplicate_or_regressed_acquisition_clock"
            elif gap > self.maximum_gap:
                reason = "acquisition_gap_exceeds_declared_limit"
        if reason:
            self.interruptions[reason] += 1
            closed = self._close(reason)
            if closed:
                results.append(closed)
            self.consecutive = 0
            self.last_included = None
            if reason == "noncontinuous_phase":
                self.started_measured = False
            if reason in ("noncontinuous_phase", "unavailable_or_malformed_reading", "duplicate_or_regressed_acquisition_clock"):
                return results
        self.last_included = reading["monotonic_seconds"]
        self.window.add(reading)
        if self.window.last["monotonic_seconds"] - self.window.first["monotonic_seconds"] >= self.policy.window_seconds:
            closed = self._close("observed_window_complete")
            results.append(closed)
            self.window.add(reading)  # explicitly shared endpoint, not another raw acquisition
        return results

    def finish(self) -> dict | None:
        """Retain the final incomplete window without mistaking it for a plateau."""

        return self._close("end_of_saved_series_partial_window")

    def report(self, *, eligible_protocol: bool, completed_block: bool) -> dict:
        """Distinguish candidate observations, partial blocks and unavailable data."""

        enough = self.longest_consecutive >= self.policy.consecutive_windows
        clock_ok = not self.interruptions["duplicate_or_regressed_acquisition_clock"]
        candidate = enough and clock_ok and eligible_protocol
        status = "unavailable" if not self.total.count else "not_eligible_protocol" if not eligible_protocol else (
            "candidate_plateau_in_completed_block" if candidate and completed_block else
            "candidate_plateau_in_partial_block" if candidate else "no_candidate_plateau_demonstrated")
        return {"status": status, "candidate_plateau_observed": candidate,
                "completed_block": completed_block, "eligible_continuous_single_pair_protocol": eligible_protocol,
                "temperature": self.total.report(), "sample_context_phases": {name: value.report() for name, value in self.phases.items()},
                "window_count": self.window_count, "qualifying_window_count": self.qualifying_count,
                "longest_consecutive_qualifying_windows": self.longest_consecutive,
                "interruptions": dict(self.interruptions), "maximum_allowed_gap_seconds": self.maximum_gap,
                "limit": "sampled candidate plateau under declared exploratory criteria; not equilibrium, thermal causality or sustained-performance acceptance"}


class FlagTransitions:
    """Retain sampled states/transitions without inventing continuous exposure."""

    def __init__(self, maximum_gap_seconds: float):
        """Keep only the preceding mask/time plus per-bit acquisition counts."""

        self.maximum_gap_seconds = maximum_gap_seconds
        self.previous = self.first = self.last = None
        self.statuses, self.current_counts, self.historical_counts = Counter(), Counter(), Counter()
        self.count = self.transitions = self.gaps = self.clock_anomalies = self.historical_clearances = 0
        self.unknown_bits = 0

    def add(self, reading: dict) -> dict | None:
        """Compare actual consecutive acquisitions; outages break transition timing."""

        self.statuses[str(reading.get("status", "unknown"))] += 1
        if reading.get("status") not in ("available", "legacy_without_acquisition_time"):
            self.previous = None
            return None
        try:
            decoded = decode_throttling_mask(reading["value"])
        except (ValueError, KeyError):
            self.statuses["malformed_mask"] += 1
            self.previous = None
            return None
        instant = reading.get("monotonic_seconds")
        if type(instant) not in (int, float) or not math.isfinite(instant):
            instant = None
        point = {**decoded, "monotonic_seconds": instant, "captured_utc": reading.get("captured_utc"),
                 "availability": reading["status"]}
        self.first = self.first or point
        self.last = point
        self.count += 1
        self.unknown_bits |= decoded["mask"] & ~KNOWN_FLAG_MASK
        for name, active in decoded["current"].items():
            self.current_counts[name] += active
        for name, active in decoded["historical"].items():
            self.historical_counts[name] += active
        event = None
        if self.previous is not None:
            before = self.previous
            gap = instant - before["monotonic_seconds"] if instant is not None and before["monotonic_seconds"] is not None else None
            contiguous = gap is not None and 0 < gap <= self.maximum_gap_seconds
            if gap is not None and gap <= 0:
                self.clock_anomalies += 1
            elif gap is not None and gap > self.maximum_gap_seconds:
                self.gaps += 1
            if decoded["mask"] != before["mask"]:
                self.transitions += 1
                cleared_history = [name for name in decoded["historical"] if before["historical"][name] and not decoded["historical"][name]]
                self.historical_clearances += bool(cleared_history)
                event = {"previous": before, "observed": point, "acquisition_gap_seconds": gap,
                         "transition_bracket_contiguous": contiguous,
                         "current_set": [name for name in decoded["current"] if decoded["current"][name] and not before["current"][name]],
                         "current_cleared": [name for name in decoded["current"] if before["current"][name] and not decoded["current"][name]],
                         "historical_newly_set": [name for name in decoded["historical"] if decoded["historical"][name] and not before["historical"][name]],
                         "historical_cleared_anomaly": cleared_history,
                         "limit": "change observed between samples; exact onset/cause/exposure duration unavailable"}
        self.previous = point
        return event

    def report(self) -> dict:
        """Historical bits already set at the first reading are not new events."""

        return {"status": "observed" if self.count else "unavailable", "availability_counts": dict(self.statuses),
                "mask_sample_count": self.count, "first": self.first, "last": self.last,
                "current_active_sample_counts": dict(self.current_counts), "historical_set_sample_counts": dict(self.historical_counts),
                "transition_count": self.transitions, "large_acquisition_gaps": self.gaps, "clock_anomalies": self.clock_anomalies,
                "historical_clearance_anomalies": self.historical_clearances, "unknown_bits_hex": hex(self.unknown_bits),
                "active_duration_seconds": None, "duration_status": "unavailable_between_sample_states_not_continuous_measurement"}


def report_thermal_readings(observations, experiments: list[dict], output_dir, *, policy: ThermalAnalysisPolicy | None = None) -> dict:
    """Reconstruct thermal evidence entirely from the saved raw report journal.

    Each group keeps source/unit/scope/segment identity. Every emitted window
    and transition is streamed to gzip, not accumulated over a multi-day run.
    No target library imports, sensor queries, OS changes or raw pruning occur.
    """

    from pathlib import Path
    from .saved_attempts import _json
    policy = policy or ThermalAnalysisPolicy()
    if not isinstance(policy, ThermalAnalysisPolicy):
        raise ValueError("thermal report policy must be ThermalAnalysisPolicy")
    output = Path(output_dir)
    temperature, flags, contexts, issues = {}, {}, {}, []
    schedules = {(experiment["identity"], block["path"]): (experiment, block)
                 for experiment in experiments for block in experiment["blocks"]}
    with gzip.open(output / "thermal-windows.jsonl.gz", "xt", encoding="utf-8") as windows, \
            gzip.open(output / "throttle-transitions.jsonl.gz", "xt", encoding="utf-8") as transitions, \
            gzip.open(observations, "rt", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            fields, board = record["raw_csv_fields"], record["observations"].get("board", {})
            if not isinstance(board, dict):
                issues.append({"journal": record.get("journal"), "csv_line": record.get("csv_line"),
                               "reason": "malformed board observations retained in raw journal"})
                board = {}
            experiment, block = schedules.get((record["experiment_id"], record["block_path"]), (None, None))
            if experiment is None:
                continue
            interval = experiment["manifest"]["observation"]["board_interval_seconds"]
            for name in ("soc_temperature_c", "throttling_flags"):
                reading = board.get(name)
                if reading is None and name == "throttling_flags":
                    raw = fields.get("throttled")
                    reading = {"value": raw, "status": "legacy_without_acquisition_time" if raw else "unavailable",
                               "source": "legacy CSV throttled (acquisition time unavailable)", "unit": "firmware_bitmask", "scope": "board",
                               "captured_utc": fields.get("captured_utc")}
                elif reading is None:
                    reading = {"value": None, "status": "missing_saved_sensor_observation",
                               "source": "missing saved SoC sensor observation", "unit": "degrees_Celsius", "scope": "board_soc"}
                if not isinstance(reading, dict):
                    continue
                if name == "soc_temperature_c" and (reading.get("unit") != "degrees_Celsius" or reading.get("scope") != "board_soc"):
                    reading = {**reading, "status": "invalid_temperature_unit_or_scope"}
                elif name == "throttling_flags" and (reading.get("unit") != "firmware_bitmask" or reading.get("scope") != "board"):
                    reading = {**reading, "status": "invalid_firmware_unit_or_scope"}
                identity = (record["experiment_id"], record["block_path"], fields.get("segment_id"),
                            reading.get("source"), reading.get("scope"), reading.get("unit"))
                context = {"experiment_id": identity[0], "block_path": identity[1], "segment_id": identity[2],
                           "source": identity[3], "scope": identity[4], "unit": identity[5],
                           "elapsed_anchor_monotonic_seconds": fields.get("elapsed_anchor_monotonic_seconds")}
                contexts[identity] = experiment, block, context
                if name == "soc_temperature_c":
                    if identity not in temperature:
                        temperature[identity] = TemperatureWindows(policy, interval)
                    series = temperature[identity]
                    for window in series.add(reading, fields.get("phase", "unknown")):
                        windows.write(json.dumps({**context, **window}, separators=(",", ":"), allow_nan=False) + "\n")
                else:
                    if identity not in flags:
                        flags[identity] = FlagTransitions(interval * policy.maximum_gap_factor)
                    series = flags[identity]
                    event = series.add(reading)
                    if event:
                        transitions.write(json.dumps({**context, **event}, separators=(",", ":"), allow_nan=False) + "\n")
        for identity, series in temperature.items():
            final = series.finish()
            if final:
                windows.write(json.dumps({**contexts[identity][2], **final}, separators=(",", ":"), allow_nan=False) + "\n")
    reports = []
    for identity, series in temperature.items():
        experiment, block, context = contexts[identity]
        eligible = (experiment["manifest"]["kind"] in ("sustained", "persistent") and len(block["pairs"]) == 1
                    and experiment["manifest"]["thermal"]["mode"] in ("stable_before_block", "uncontrolled"))
        terminal = experiment["root"] / block["path"] / "benchmark-session.json"
        completed = False
        if terminal.is_file():
            try:
                completed = _json(terminal).get("status") == "complete"
            except (ValueError, OSError):
                pass  # Corrupt terminal bytes cannot establish a completed block.
        reports.append({**context, **series.report(eligible_protocol=eligible, completed_block=completed)})
    return {"thermal_analysis_schema_version": 1, "policy": asdict(policy), "policy_classification": "exploratory_report_criteria_not_pilot_calibrated",
            "temperature_groups": reports, "throttling_groups": [{**contexts[key][2], **series.report()} for key, series in flags.items()],
            "window_journal": "thermal-windows.jsonl.gz", "transition_journal": "throttle-transitions.jsonl.gz",
            "raw_source": Path(observations).name, "issues": issues, "raw_samples_deleted": False}
