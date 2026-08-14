"""Parse SUCHAI-1 TLE history and assign the nearest epoch."""

from __future__ import annotations

from bisect import bisect_left
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from .errors import DataValidationError
from .models import TLERecord, TLESelection


def tle_checksum(line: str) -> int:
    """Calculate the standard modulo-10 checksum for the first 68 columns."""

    if len(line) != 69:
        raise DataValidationError(f"TLE line must contain exactly 69 columns, found {len(line)}")
    return sum(int(character) if character.isdigit() else 1 if character == "-" else 0 for character in line[:68]) % 10


def validate_tle_line(line: str, expected_line_number: int) -> None:
    """Validate fixed width, line designator, and checksum."""

    if len(line) != 69:
        raise DataValidationError(
            f"TLE line {expected_line_number} must contain 69 columns, found {len(line)}"
        )
    if not line.startswith(f"{expected_line_number} "):
        raise DataValidationError(f"expected TLE line {expected_line_number}, found {line[:2]!r}")
    if not line[68].isdigit() or tle_checksum(line) != int(line[68]):
        raise DataValidationError(f"invalid checksum on TLE line {expected_line_number}: {line!r}")


def parse_tle_epoch(field: str) -> datetime:
    """Convert a TLE ``YYDDD.dddddd`` epoch to a UTC datetime.

    The SGP4 convention maps years 57–99 to 1957–1999 and 00–56 to
    2000–2056. Fractional day values retain microsecond precision.
    """

    value = field.strip()
    try:
        year_2d = int(value[:2])
        day = float(value[2:])
    except (ValueError, IndexError) as exc:
        raise DataValidationError(f"invalid TLE epoch: {field!r}") from exc
    if not 1.0 <= day < 367.0:
        raise DataValidationError(f"TLE day-of-year is out of range: {field!r}")
    year = 1900 + year_2d if year_2d >= 57 else 2000 + year_2d
    return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day - 1.0)


def load_tle_history(path: str | Path) -> tuple[TLERecord, ...]:
    """Load, validate, and chronologically sort a two-line TLE history."""

    source = Path(path)
    if not source.is_file():
        raise DataValidationError(f"TLE file does not exist: {source}")
    lines = [line.rstrip("\r\n") for line in source.read_text(encoding="ascii").splitlines() if line.strip()]
    if len(lines) % 2:
        raise DataValidationError("TLE history contains an unmatched line")

    records: list[TLERecord] = []
    for offset in range(0, len(lines), 2):
        line1, line2 = lines[offset : offset + 2]
        validate_tle_line(line1, 1)
        validate_tle_line(line2, 2)
        sat1, sat2 = line1[2:7].strip(), line2[2:7].strip()
        if sat1 != sat2:
            raise DataValidationError(f"satellite-number mismatch at TLE pair {offset // 2 + 1}")
        records.append(TLERecord(line1, line2, parse_tle_epoch(line1[18:32]), sat1))

    if not records:
        raise DataValidationError("TLE history is empty")
    records.sort(key=lambda item: item.epoch)
    return tuple(records)


def select_nearest_tles(times: tuple[datetime, ...], records: tuple[TLERecord, ...]) -> TLESelection:
    """Assign each observation the TLE whose epoch has minimum time distance.

    Later TLEs are intentionally eligible because this pipeline performs
    retrospective analysis. Exact ties choose the earlier TLE deterministically.
    """

    if not records:
        raise DataValidationError("cannot select from an empty TLE history")
    epochs = [record.epoch.timestamp() for record in records]
    selected = np.empty(len(times), dtype=np.int64)
    offsets = np.empty(len(times), dtype=np.float64)
    for index, observation in enumerate(times):
        stamp = observation.timestamp()
        right = bisect_left(epochs, stamp)
        if right == 0:
            choice = 0
        elif right == len(epochs):
            choice = len(epochs) - 1
        else:
            left = right - 1
            choice = right if epochs[right] - stamp < stamp - epochs[left] else left
        selected[index] = choice
        offsets[index] = stamp - epochs[choice]
    return TLESelection(selected, offsets)


def audit_tle_history(
    path: str | Path,
    observation_times: tuple[datetime, ...],
    expected_satellite_number: str = "42788",
    maximum_assignment_age_hours: float = 24.0,
) -> dict:
    """Audit source integrity, SGP4 usability, and observation-time coverage."""

    from collections import Counter
    from sgp4.api import Satrec

    source = Path(path)
    raw_lines = [line.rstrip("\r\n") for line in source.read_text(encoding="ascii").splitlines() if line.strip()]
    raw_epochs = [parse_tle_epoch(raw_lines[index][18:32]) for index in range(0, len(raw_lines), 2)]
    records = load_tle_history(source)
    satellite_numbers = Counter(record.satellite_number for record in records)
    epoch_seconds = np.asarray([record.epoch.timestamp() for record in records])
    gaps_hours = np.diff(epoch_seconds) / 3600.0
    selection = select_nearest_tles(observation_times, records)
    absolute_assignment_hours = np.abs(selection.offset_seconds) / 3600.0
    sgp4_errors = Counter()
    for record in records:
        satellite = Satrec.twoline2rv(record.line1, record.line2)
        error, _, _ = satellite.sgp4(satellite.jdsatepoch, satellite.jdsatepochF)
        sgp4_errors[int(error)] += 1
    ordered_violations = sum(
        current < previous for previous, current in zip(raw_epochs, raw_epochs[1:])
    )
    duplicate_epochs = len(records) - len(set(record.epoch for record in records))
    criteria = {
        "satellite_identity": {
            "passed": set(satellite_numbers) == {expected_satellite_number},
            "expected": expected_satellite_number, "observed": dict(satellite_numbers),
        },
        "source_epoch_order": {"passed": ordered_violations == 0, "violations": ordered_violations},
        "unique_epochs": {"passed": duplicate_epochs == 0, "duplicates": duplicate_epochs},
        "sgp4_at_epoch": {"passed": set(sgp4_errors) == {0}, "error_codes": {str(key): value for key, value in sgp4_errors.items()}},
        "observation_coverage": {
            "passed": records[0].epoch <= min(observation_times) and max(observation_times) <= records[-1].epoch,
            "observation_start_utc": min(observation_times).isoformat(),
            "observation_end_utc": max(observation_times).isoformat(),
        },
        "assignment_age": {
            "passed": bool(np.max(absolute_assignment_hours) <= maximum_assignment_age_hours),
            "limit_hours": maximum_assignment_age_hours,
            "maximum_hours": float(np.max(absolute_assignment_hours)),
        },
    }
    return {
        "status": "pass" if all(item["passed"] for item in criteria.values()) else "fail",
        "records": len(records), "raw_lines": len(raw_lines),
        "first_epoch_utc": records[0].epoch.isoformat(),
        "last_epoch_utc": records[-1].epoch.isoformat(),
        "satellite_numbers": dict(satellite_numbers),
        "gap_hours": {
            "minimum": float(np.min(gaps_hours)), "median": float(np.median(gaps_hours)),
            "p95": float(np.quantile(gaps_hours, 0.95)), "p99": float(np.quantile(gaps_hours, 0.99)),
            "maximum": float(np.max(gaps_hours)),
        },
        "assignment": {
            "observations": len(observation_times),
            "unique_tles_used": int(len(np.unique(selection.indices))),
            "earlier_or_equal": int(np.count_nonzero(selection.offset_seconds >= 0)),
            "later": int(np.count_nonzero(selection.offset_seconds < 0)),
            "absolute_age_hours": {
                "median": float(np.median(absolute_assignment_hours)),
                "p95": float(np.quantile(absolute_assignment_hours, 0.95)),
                "p99": float(np.quantile(absolute_assignment_hours, 0.99)),
                "maximum": float(np.max(absolute_assignment_hours)),
            },
        },
        "criteria": criteria,
    }
