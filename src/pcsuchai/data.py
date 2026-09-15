"""Load and validate trusted SUCHAI-1 instrument products."""

from __future__ import annotations

import csv
import gzip
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .errors import DataValidationError
from .models import Measurements

TRUSTED_COLUMNS = (
    "Particles counter",
    "Plasma temperature",
    "Plasma voltage",
    "Sweep voltage",
    "header",
    "time",
    "Plasma current",
    "Electron density 300K",
    "Electron density 3000K",
)


def load_measurements(path: str | Path) -> Measurements:
    """Load trusted measurements from the source table.

    The historical file uses tab delimiters despite its ``.csv`` suffix. Only
    columns listed in :data:`TRUSTED_COLUMNS` are read. Existing latitude,
    longitude, day/night, anomaly, grouping, and season columns are ignored.

    Parameters
    ----------
    path:
        Path to the original tab-separated table or its byte-exact gzip snapshot.

    Returns
    -------
    Measurements
        Validated observations in their original order, including duplicate
        timestamps.
    """

    source = Path(path)
    if not source.is_file():
        raise DataValidationError(f"measurement file does not exist: {source}")

    values: dict[str, list[float]] = {
        name: [] for name in TRUSTED_COLUMNS if name not in {"header", "time"}
    }
    times: list[datetime] = []
    headers: list[str] = []
    rows: list[int] = []

    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [name for name in TRUSTED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise DataValidationError(f"missing trusted columns: {', '.join(missing)}")

        for source_row, row in enumerate(reader, start=2):
            try:
                parsed_time = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                parsed = {name: float(row[name]) for name in values}
            except (TypeError, ValueError) as exc:
                raise DataValidationError(f"invalid trusted value at source row {source_row}: {exc}") from exc
            times.append(parsed_time)
            headers.append(row["header"].strip())
            rows.append(source_row)
            for name, value in parsed.items():
                values[name].append(value)

    if not times:
        raise DataValidationError("measurement file contains no observations")

    return Measurements(
        times=tuple(times),
        particle_counts=np.asarray(values["Particles counter"], dtype=np.float64),
        plasma_temperature=np.asarray(values["Plasma temperature"], dtype=np.float64),
        plasma_voltage=np.asarray(values["Plasma voltage"], dtype=np.float64),
        sweep_voltage=np.asarray(values["Sweep voltage"], dtype=np.float64),
        plasma_current=np.asarray(values["Plasma current"], dtype=np.float64),
        electron_density_300k=np.asarray(values["Electron density 300K"], dtype=np.float64),
        electron_density_3000k=np.asarray(values["Electron density 3000K"], dtype=np.float64),
        headers=tuple(headers),
        source_rows=np.asarray(rows, dtype=np.int64),
    )


def audit_measurements(measurements: Measurements) -> dict:
    """Describe trusted instrument values and enforce structural invariants."""

    numeric_fields = (
        "particle_counts", "plasma_temperature", "plasma_voltage", "sweep_voltage",
        "plasma_current", "electron_density_300k", "electron_density_3000k",
    )
    fields = {}
    for name in numeric_fields:
        values = np.asarray(getattr(measurements, name), dtype=float)
        finite = np.isfinite(values)
        fields[name] = {
            "rows": len(values), "finite": int(np.count_nonzero(finite)),
            "nonfinite": int(np.count_nonzero(~finite)),
            "nan": int(np.count_nonzero(np.isnan(values))),
            "positive_infinity": int(np.count_nonzero(np.isposinf(values))),
            "negative_infinity": int(np.count_nonzero(np.isneginf(values))),
            "finite_minimum": float(np.min(values[finite])) if np.any(finite) else None,
            "finite_maximum": float(np.max(values[finite])) if np.any(finite) else None,
        }
    criteria = {
        "nonempty": len(measurements) > 0,
        "timezones_are_utc": all(item.utcoffset() == UTC.utcoffset(item) for item in measurements.times),
        "times_nondecreasing": all(current >= previous for previous, current in zip(measurements.times, measurements.times[1:])),
        "source_rows_unique": len(set(map(int, measurements.source_rows))) == len(measurements),
        "particle_counts_finite": fields["particle_counts"]["finite"] == len(measurements),
        "particle_counts_nonnegative": bool(np.all(measurements.particle_counts >= 0)),
        "all_field_lengths_match": all(len(getattr(measurements, name)) == len(measurements) for name in numeric_fields),
    }
    return {
        "status": "pass" if all(criteria.values()) else "fail",
        "rows": len(measurements), "first_time_utc": measurements.times[0].isoformat(),
        "last_time_utc": measurements.times[-1].isoformat(),
        "duplicate_timestamps": len(measurements.times) - len(set(measurements.times)),
        "criteria": criteria, "fields": fields,
        "interpretation": (
            "Non-finite trusted instrument values are preserved and counted. Plot and "
            "analysis selections exclude them where finite numeric values are required."
        ),
    }
