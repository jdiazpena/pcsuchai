from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.data import load_measurements
from pcsuchai.workload import describe_selection, select_measurements, selection_indices


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("rows", [1, 2, 10, 101])
def test_spread_indices_are_exact_unique_ordered_and_cover_endpoints(rows):
    for size in range(1, rows + 1):
        indices = selection_indices(rows, size, "spread")
        assert len(indices) == size
        assert len(set(indices)) == size
        assert np.all(np.diff(indices) > 0)
        assert indices.min() >= 0 and indices.max() < rows
        if size > 1:
            assert indices[0] == 0 and indices[-1] == rows - 1


@pytest.mark.parametrize("size,method", [(0, "prefix"), (True, "spread"), (100_000, "spread"), (1, "full"), (1.5, "spread"), (1, "unknown")])
def test_invalid_or_unavailable_workload_is_not_silently_reduced(size, method):
    with pytest.raises(ValueError):
        selection_indices(100, size, method)


def test_scaling_selection_preserves_every_trusted_array_and_original_row_ids():
    original = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")
    indices = selection_indices(len(original), 100, "spread")
    selected = select_measurements(original, 100, "spread")
    for field in fields(original):
        expected = np.asarray(getattr(original, field.name))[indices]
        actual = np.asarray(getattr(selected, field.name))
        if actual.dtype.kind in "fc":
            assert np.array_equal(actual, expected, equal_nan=True)
        else:
            assert np.array_equal(actual, expected)
    coverage = describe_selection(original, selected, 100, "spread")
    assert coverage["source_rows"] == original.source_rows[indices].tolist()
    assert coverage["first_time_utc"] == original.times[0].isoformat()
    assert coverage["last_time_utc"] == original.times[-1].isoformat()
    full = select_measurements(original, None, "full")
    assert len(full) - len(set(full.times)) == 255
    assert np.isposinf(full.plasma_current).sum() == 126
