import json

import numpy as np
import pytest

from pcsuchai.session_statistics import session_ratio, session_statistics


def test_single_hot_loop_is_not_independent_sessions():
    report = session_statistics({"one": [1.0] * 100}, resamples=100)
    assert report["attempt_count"] == 100
    assert report["session_count"] == 1
    assert report["uncertainty"]["status"] == "unavailable"
    assert report["uncertainty"]["intervals"] == {}
    assert report["attempt_p95"] == 1.0


def test_equal_session_weight_and_deterministic_intervals():
    values = {"short": [1.0], "long": [100.0] * 100}
    report = session_statistics(values, seed=7, resamples=100)
    assert report["median_of_session_medians"] == 50.5
    assert report["attempt_median"] == 100.0
    assert report["uncertainty"]["small_session_sample"]
    assert report == session_statistics(values, seed=7, resamples=100)
    json.dumps(report, allow_nan=False)


def test_speedup_resamples_sessions_not_adjacent_runs():
    report = session_ratio({"a": [4.0] * 10, "b": [8.0] * 10},
                           {"x": [2.0] * 10, "y": [4.0] * 10}, resamples=100)
    assert report["ratio"] == 2.0
    assert report["uncertainty"]["method"] == "independent_session_bootstrap"
    assert report["uncertainty"]["interval"] is not None
    missing = session_ratio({"a": [4.0]}, {"x": [2.0]}, resamples=100)
    assert missing["ratio"] == 2.0
    assert missing["uncertainty"]["interval"] is None


def test_paired_observation_levels_require_same_sessions():
    assert session_ratio({"a": [4]}, {"b": [2]}, paired=True, resamples=100)["status"] == "unavailable"
    paired = session_ratio({"a": [2], "b": [4]}, {"a": [4], "b": [8]}, paired=True, resamples=100)
    assert paired["ratio"] == 0.5
    assert paired["uncertainty"]["interval"] == [0.5, 0.5]


@pytest.mark.parametrize("values", [{"a": [np.nan]}, {"a": [0]}, {"a": [-1]}, {"a": [[1]]}])
def test_invalid_duration_samples_are_not_zero_filled(values):
    with pytest.raises(ValueError):
        session_statistics(values, resamples=100)


def test_empty_samples_are_unavailable():
    result = session_statistics({}, resamples=100)
    assert result["median_of_session_medians"] is None
    assert result["attempt_p95"] is None
    assert session_ratio({}, {"a": [1]}, resamples=100)["status"] == "unavailable"
