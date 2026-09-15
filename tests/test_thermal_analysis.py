"""Declared synthetic sensor/firmware replays, not actual Pi acceptance."""

import gzip
import json
from pathlib import Path

import pytest

from pcsuchai.firmware import decode_throttling_mask, parse_throttling_mask
from pcsuchai.thermal_analysis import FlagTransitions, TemperatureWindows, ThermalAnalysisPolicy, report_thermal_readings


def reading(value, instant, *, status="available"):
    return {"value": value, "monotonic_seconds": instant, "status": status,
            "captured_utc": "2026-09-15T00:00:00+00:00", "source": "synthetic-replay",
            "unit": "degrees_Celsius", "scope": "board_soc"}


@pytest.mark.parametrize("bad", [True, -1, 1.0, "4", "-0x1", "0x100000000", "0xZZ"])
def test_mask_parser_does_not_coerce_bad_values(bad):
    with pytest.raises(ValueError):
        parse_throttling_mask(bad)


def test_current_and_historical_flags_are_not_equivalent():
    decoded = decode_throttling_mask("0x50000")
    assert not any(decoded["current"].values())
    assert decoded["historical"]["currently_throttled"]
    assert decoded["historical"]["undervoltage_detected"]
    assert decode_throttling_mask(0)["mask"] == 0
    assert decode_throttling_mask(1 << 30)["unknown_bits_hex"] == "0x40000000"


@pytest.mark.parametrize("value", [0, float("nan"), True, -1])
def test_invalid_window_policy_rejected(value):
    with pytest.raises(ValueError):
        ThermalAnalysisPolicy(window_seconds=value)


def test_irregular_acquisition_windows_use_observed_span_not_nominal_time():
    series = TemperatureWindows(ThermalAnalysisPolicy(window_seconds=10), 5)
    windows = []
    for instant in (0, 4, 10, 14, 20):
        windows += series.add(reading(42, instant), "measured")
    assert len(windows) == 2 and all(window["qualifies_low_slope_small_range"] for window in windows)
    assert series.total.count == 5  # shared window boundary is NOT another acquisition
    series.finish()
    result = series.report(eligible_protocol=True, completed_block=True)
    assert result["status"] == "candidate_plateau_in_completed_block"
    assert result["longest_consecutive_qualifying_windows"] == 2
    assert series.report(eligible_protocol=True, completed_block=False)["status"] == "candidate_plateau_in_partial_block"
    assert not series.report(eligible_protocol=False, completed_block=True)["candidate_plateau_observed"]


def test_heating_range_and_short_stopped_series_do_not_establish_plateau():
    series = TemperatureWindows(ThermalAnalysisPolicy(window_seconds=10), 5)
    for instant in (0, 5, 10, 15, 20):
        series.add(reading(40 + instant, instant), "measured")
    series.finish()
    assert not series.report(eligible_protocol=True, completed_block=False)["candidate_plateau_observed"]
    assert series.total.report()["linear_slope_per_second"] == 1


@pytest.mark.parametrize("fault", ["outage", "gap", "clock", "warmup"])
def test_missing_gap_clock_and_noncontinuous_phase_break_evidence(fault):
    series = TemperatureWindows(ThermalAnalysisPolicy(window_seconds=10), 5)
    for instant in (0, 5, 10):
        series.add(reading(42, instant), "measured")
    if fault == "outage":
        event = reading(None, 12, status="unsupported")
        windows = series.add(event, "measured")
        restart = (15, 20, 25)
    elif fault == "gap":
        windows = series.add(reading(42, 30), "idle")
        restart = (35, 40)
    elif fault == "clock":
        windows = series.add(reading(42, 9), "measured")
        restart = (15, 20, 25)
    else:
        windows = series.add(reading(42, 12), "warmup")
        restart = (15, 20, 25)
    assert windows and not windows[0]["qualifies_low_slope_small_range"]
    for instant in restart:
        series.add(reading(42, instant), "measured")
    series.finish()
    assert not series.report(eligible_protocol=True, completed_block=True)["candidate_plateau_observed"]


def test_idle_baseline_cannot_be_mistaken_for_sustained_work():
    series = TemperatureWindows(ThermalAnalysisPolicy(window_seconds=10), 5)
    for instant in range(0, 100, 5):
        assert not series.add(reading(40, instant), "idle")
    assert not series.finish()
    assert series.report(eligible_protocol=True, completed_block=True)["qualifying_window_count"] == 0


def test_historical_first_sample_and_outage_do_not_invent_event_time_or_exposure():
    series = FlagTransitions(5)
    assert series.add(reading(0x40000, 0)) is None
    assert series.add(reading(0x40004, 2))["current_set"] == ["currently_throttled"]
    assert series.add(reading(0x40000, 4))["current_cleared"] == ["currently_throttled"]
    series.add(reading(None, 5, status="unsupported"))
    assert series.add(reading(0x40004, 20)) is None
    result = series.report()
    assert result["transition_count"] == 2
    assert result["active_duration_seconds"] is None
    assert result["first"]["historical"]["currently_throttled"]


def test_historical_bit_clearance_and_gap_are_reported_as_ambiguous():
    series = FlagTransitions(5)
    series.add(reading(0x40000, 0))
    event = series.add(reading(0, 20))
    assert event["historical_cleared_anomaly"] == ["currently_throttled"]
    assert not event["transition_bracket_contiguous"]
    assert series.report()["large_acquisition_gaps"] == 1


def test_missing_sensor_and_legacy_mask_remain_explicit(tmp_path):
    observations = tmp_path / "observations.jsonl.gz"
    experiment = {"identity": "e", "root": tmp_path, "blocks": [{"path": "b", "pairs": ["astropy-apexpy"]}],
                  "manifest": {"kind": "sustained", "thermal": {"mode": "uncontrolled"},
                               "observation": {"board_interval_seconds": 2}}}
    with gzip.open(observations, "wt") as stream:
        stream.write(json.dumps({"experiment_id": "e", "block_path": "b", "raw_csv_fields": {
            "phase": "measured", "segment_id": "s", "throttled": "0x40000"},
            "observations": {"board": {"soc_temperature_c": reading(None, 0, status="unsupported")}}}) + "\n")
    result = report_thermal_readings(observations, [experiment], tmp_path)
    assert result["temperature_groups"][0]["status"] == "unavailable"
    flags = result["throttling_groups"][0]
    assert flags["availability_counts"]["legacy_without_acquisition_time"] == 1
    assert not flags["first"]["current"]["currently_throttled"]
    assert flags["first"]["monotonic_seconds"] is None
    assert not result["raw_samples_deleted"]


def test_thermal_png_keeps_current_history_and_window_metadata(tmp_path):
    from PIL import Image
    from pcsuchai.thermal_plotting import render_thermal_plots

    observations = tmp_path / "observations.jsonl.gz"
    experiment = {"identity": "e", "root": tmp_path, "blocks": [{"path": "b", "pairs": ["astropy-apexpy"]}],
                  "manifest": {"kind": "sustained", "thermal": {"mode": "uncontrolled"},
                               "observation": {"board_interval_seconds": 5}}}
    with gzip.open(observations, "wt") as stream:
        for instant in (100, 105, 110, 115, 120):
            mask = {**reading(0x40000 if instant < 115 else 0x40004, instant),
                    "unit": "firmware_bitmask", "source": "vcgencmd get_throttled", "scope": "board"}
            stream.write(json.dumps({"experiment_id": "e", "block_path": "b", "raw_csv_fields": {
                "phase": "measured", "segment_id": "s", "elapsed_anchor_monotonic_seconds": "100"},
                "observations": {"board": {"soc_temperature_c": reading(42, instant), "throttling_flags": mask}}}) + "\n")
    analysis = report_thermal_readings(observations, [experiment], tmp_path, policy=ThermalAnalysisPolicy(window_seconds=10))
    assert analysis["temperature_groups"][0]["status"] == "candidate_plateau_in_partial_block"
    plots = render_thermal_plots(observations, analysis, tmp_path)
    assert len(plots) == 1
    assert {channel["identity"][0] for channel in plots[0]["channels"]} == {
        "slope_c_per_minute", "temperature_range_c", "current", "historical"}
    assert all(not channel["raw_samples_deleted"] for channel in plots[0]["channels"])
    with Image.open(tmp_path / plots[0]["path"]) as image:
        image.load()
        assert image.size == (1000, 1000)


def test_large_timeline_uses_constant_memory_not_sample_history():
    series = TemperatureWindows(ThermalAnalysisPolicy(window_seconds=10), 1)
    for instant in range(10000):
        series.add(reading(42, instant), "measured")
    assert series.total.count == 10000
    assert series.window.count <= 11
    assert len(series.phases) == 1
    assert all(not isinstance(value, list) for value in vars(series).values())


def test_wrong_temperature_units_cannot_qualify_windows(tmp_path):
    observations = tmp_path / "observations.jsonl.gz"
    experiment = {"identity": "e", "root": tmp_path, "blocks": [{"path": "b", "pairs": ["astropy-apexpy"]}],
                  "manifest": {"kind": "sustained", "thermal": {"mode": "uncontrolled"},
                               "observation": {"board_interval_seconds": 5}}}
    with gzip.open(observations, "wt") as stream:
        for instant in range(0, 30, 5):
            temperature = {**reading(42, instant), "unit": "kelvin"}
            stream.write(json.dumps({"experiment_id": "e", "block_path": "b", "raw_csv_fields": {"phase": "measured", "segment_id": "s"},
                                     "observations": {"board": {"soc_temperature_c": temperature}}}) + "\n")
    result = report_thermal_readings(observations, [experiment], tmp_path, policy=ThermalAnalysisPolicy(window_seconds=10))
    summary = result["temperature_groups"][0]
    assert summary["status"] == "unavailable"
    assert not summary["candidate_plateau_observed"]
    assert summary["temperature"]["availability_counts"]["invalid_temperature_unit_or_scope"] == 6


def test_missing_or_malformed_board_record_is_retained_without_false_plateau(tmp_path):
    observations = tmp_path / "observations.jsonl.gz"
    experiment = {"identity": "e", "root": tmp_path, "blocks": [{"path": "b", "pairs": ["astropy-apexpy"]}],
                  "manifest": {"kind": "sustained", "thermal": {"mode": "uncontrolled"},
                               "observation": {"board_interval_seconds": 5}}}
    with gzip.open(observations, "wt") as stream:
        stream.write(json.dumps({"experiment_id": "e", "block_path": "b", "raw_csv_fields": {"phase": "measured", "segment_id": "s"},
                                 "observations": {"board": []}}) + "\n")
    result = report_thermal_readings(observations, [experiment], tmp_path)
    assert result["temperature_groups"][0]["status"] == "unavailable"
    assert result["issues"]
