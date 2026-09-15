"""Deterministic scaling selections without rewriting trusted input tables."""

from __future__ import annotations

from dataclasses import fields

import numpy as np

from .models import Measurements


def selection_indices(rows: int, size: int | None, method: str = "prefix") -> np.ndarray:
    """Select original observation indices, preserving order and row identity.

    ``spread`` uses integer-spaced indices including both endpoints for sizes
    greater than one. This spans the source interval, not an assertion of equal
    geographical, temporal or anomaly coverage. A one-row spread selects the
    middle observation. Prefix remains the backwards-compatible smoke test.
    Requested sizes exceeding the available rows fail rather than silently
    benchmarking less work. Full selection requires an unset size.
    """

    if type(rows) is not int or rows < 1:
        raise ValueError("available rows must be a positive integer")
    if method not in ("full", "prefix", "spread"):
        raise ValueError("selection method must be full, prefix or spread")
    if size is not None and (type(size) is not int or size < 1 or size > rows):
        raise ValueError("selection size must be a positive integer no larger than the input")
    if method == "full" and size is not None:
        raise ValueError("full selection requires size=null")
    if size is None or size == rows:
        return np.arange(rows, dtype=np.int64)
    if method == "prefix":
        return np.arange(size, dtype=np.int64)
    if size == 1:
        return np.asarray([rows // 2], dtype=np.int64)
    # Integer arithmetic avoids floating-point index rounding and duplicates.
    return np.asarray([i * (rows - 1) // (size - 1) for i in range(size)], dtype=np.int64)


def select_measurements(measurements: Measurements, size: int | None, method: str) -> Measurements:
    """Apply one selection to every trusted field, retaining source row IDs.

    Duplicate timestamps and legitimate non-finite values are neither filtered
    nor merged. Inputs are freshly loaded by each pipeline invocation; this
    helper introduces no persistent cache or model-object reuse.
    """

    indices = selection_indices(len(measurements), size, method)
    values = {}
    for field in fields(measurements):
        value = getattr(measurements, field.name)
        values[field.name] = tuple(value[int(index)] for index in indices) if isinstance(value, tuple) else value[indices]
    return Measurements(**values)


def describe_selection(original: Measurements, selected: Measurements, size: int | None, method: str) -> dict:
    """Record actual selection identity and coverage, not inferred row counts."""

    return {
        "method": method, "requested_size": size, "available_rows": len(original),
        "selected_rows": len(selected), "source_rows": selected.source_rows.tolist(),
        "first_time_utc": selected.times[0].isoformat(),
        "last_time_utc": selected.times[-1].isoformat(),
        "duplicate_timestamps": len(selected) - len(set(selected.times)),
        "coverage_interpretation": "source-index coverage; not region-stratified sampling",
    }
