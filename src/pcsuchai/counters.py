"""Perf event accounting that preserves availability, coverage and raw precision."""

from __future__ import annotations

import math
import gzip
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _number(text: str):
    """Keep integer event counts exact even above IEEE-754's integer range."""

    try:
        value = Decimal(text.replace(",", "").removesuffix("%"))
        if not value.is_finite():
            return None
        return int(value) if value == value.to_integral_value() else float(value)
    except InvalidOperation:
        return None


def event_scope(event: str) -> str:
    """Identify user/kernel counting modifiers, retaining unspecified scope."""

    modifiers = event.rsplit(":", 1)[1] if ":" in event else ""
    user, kernel = "u" in modifiers, "k" in modifiers
    if user and not kernel:
        return "user"
    if kernel and not user:
        return "kernel"
    return "user_and_kernel"


def parse_counter_records(path: str | Path, *, no_scale: bool = True,
                          minimum_coverage_percent: float = 95.0) -> dict:
    """Parse our aggregate, single-run semicolon perf format, retaining each row.

    Use ``perf stat --no-scale --no-big-num -x ';'`` without interval/repeat/
    per-CPU output. Counter run time is nanoseconds from perf's read accounting.
    Perf prints running coverage rounded to two decimals; enabled time inferred
    from it is explicitly an estimate with a rounding interval. It is never
    labelled an exact kernel time_enabled reading. Scaled event counts are
    estimates too. Legacy normally scaled output is supported without scaling
    it twice. Unsupported/not-counted events remain distinguishable from zero.
    """

    if type(minimum_coverage_percent) not in (int, float) or not math.isfinite(minimum_coverage_percent) or not 0 < minimum_coverage_percent <= 100:
        raise ValueError("counter coverage threshold must be in (0, 100]")
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as source:
        text = source.read()
    return parse_counter_text(text, source_path=str(path), no_scale=no_scale,
                              minimum_coverage_percent=minimum_coverage_percent)


def parse_counter_text(text: str, *, source_path: str, no_scale: bool = True,
                       minimum_coverage_percent: float = 95.0) -> dict:
    """Parse saved raw text without rerunning perf or writing temporary files."""

    if type(minimum_coverage_percent) not in (int, float) or not math.isfinite(minimum_coverage_percent) or not 0 < minimum_coverage_percent <= 100:
        raise ValueError("counter coverage threshold must be in (0, 100]")
    records = []
    unparsed = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        parts = [part.strip() for part in raw_line.split(";")]
        if len(parts) < 3 or not parts[2]:
            unparsed.append({"line_number": line_number, "raw_line": raw_line})
            continue
        raw_value, unit, event = parts[:3]
        value = _number(raw_value)
        running = _number(parts[3]) if len(parts) > 3 else None
        coverage = _number(parts[4]) if len(parts) > 4 else None
        availability = "available" if value is not None and value >= 0 else "invalid_value"
        if raw_value == "<not supported>":
            availability = "unsupported"
        elif raw_value == "<not counted>":
            availability = "not_counted"
        valid_coverage = coverage is not None and 0 < coverage <= 100 and running is not None and running > 0
        quality = "acceptable" if valid_coverage and coverage >= minimum_coverage_percent else "poor_coverage" if valid_coverage else "missing_or_invalid_coverage"
        enabled = running * 100 / coverage if valid_coverage else None
        enabled_bounds = None
        if valid_coverage:
            # Coverage is a two-decimal percent, so inferred enabled time has
            # finite precision. At 100% lower coverage still bounds the error.
            lower_percent, upper_percent = max(coverage - 0.005, 0.000001), min(coverage + 0.005, 100)
            enabled_bounds = [running * 100 / upper_percent, running * 100 / lower_percent]
        scaled = value * 100 / coverage if no_scale and value is not None and valid_coverage else value if not no_scale else None
        records.append({
            "line_number": line_number, "raw_line": raw_line,
            "event": event, "scope": event_scope(event), "unit": unit or "count",
            "reported_value": value, "reported_value_scaled_by_perf": not no_scale,
            "availability": availability, "quality": quality,
            "running_time_ns": running, "running_coverage_percent": coverage,
            "enabled_time_ns_estimate": enabled,
            "enabled_time_ns_rounding_bounds": enabled_bounds,
            "enabled_time_source": "running_time / rounded running coverage (estimate)",
            "scaled_value_estimate": scaled,
            "minimum_coverage_percent": minimum_coverage_percent,
            "extra_fields": parts[5:],
        })
    return {
        "schema_version": 1, "format": "perf aggregate single-run semicolon",
        "source_path": source_path, "no_scale": no_scale,
        "events": records, "unparsed_lines": unparsed,
    }


def matched_ipc(counter_report: dict, *, simultaneous_group: bool) -> dict:
    """Compute IPC only for matched, acceptable cycles/instructions in one group.

    Separate PMUs, ambiguous duplicate events, mismatched modifiers or coverage
    cannot produce an IPC number. Counts across ARMv6/AArch64 remain descriptions
    of different instruction streams, rather than a universal efficiency score.
    """

    result = {"value": None, "unit": "instructions_per_cycle", "status": "unavailable", "reason": None}
    cycles = [event for event in counter_report["events"] if event["event"].split(":", 1)[0] in ("cycles", "cpu-cycles")]
    instructions = [event for event in counter_report["events"] if event["event"].split(":", 1)[0] == "instructions"]
    if not simultaneous_group or len(cycles) != 1 or len(instructions) != 1:
        result["reason"] = "requires one cycles and one instructions event in the same simultaneous group"
        return result
    cycles, instructions = cycles[0], instructions[0]
    if any(event["availability"] != "available" or event["quality"] != "acceptable" for event in (cycles, instructions)):
        result["reason"] = "counter unavailable or insufficient measurement coverage"
    elif cycles["scope"] != instructions["scope"]:
        result["reason"] = "different user/kernel scopes"
    elif cycles["running_coverage_percent"] != instructions["running_coverage_percent"] or cycles["running_time_ns"] != instructions["running_time_ns"]:
        result["reason"] = "counter accounting windows do not match"
    elif not cycles["reported_value"]:
        result["reason"] = "zero cycles cannot define IPC"
    else:
        result.update({"value": instructions["reported_value"] / cycles["reported_value"],
                       "status": "available", "scope": cycles["scope"]})
    return result
