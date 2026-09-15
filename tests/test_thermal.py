import csv
import gzip

import pytest

from pcsuchai.thermal import ThermalPolicy, acquire_thermal_condition, temperature_slope, thermal_safety_reason


class ReplayClock:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def policy(**overrides):
    return ThermalPolicy(**{
        "baseline_seconds": 10.0, "stable_seconds": 10.0,
        "timeout_seconds": 30.0, "sample_interval_seconds": 2.0,
        **overrides,
    })


def acquire(tmp_path, temperatures, baseline=35.0, **overrides):
    clock = ReplayClock()
    readings = iter(temperatures)
    result = acquire_thermal_condition(
        policy(**overrides), tmp_path / "trace.csv", baseline_c=baseline,
        sensor=lambda: next(readings), clock=clock.clock, sleep=clock.sleep,
    )
    with gzip.open(result["trace_path"], "rt", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return result, rows


def test_gate_requires_full_stable_window_and_retains_every_reading(tmp_path):
    result, rows = acquire(tmp_path, [35.0] * 6)
    assert result["passed"]
    assert result["elapsed_seconds"] == 10
    assert result["sample_count"] == len(rows) == 6
    assert result["status"] == "stable"
    assert rows[-1]["slope_c_per_minute"] == "0.0"


def test_one_cool_reading_does_not_pass_a_hot_history(tmp_path):
    result, rows = acquire(tmp_path, [40.0] * 5 + [35.0] * 6)
    assert result["passed"]
    assert result["elapsed_seconds"] == 20
    assert len(rows) == 11


def test_temperature_trend_prevents_gate_even_inside_band(tmp_path):
    result, rows = acquire(tmp_path, [35.0 + 0.03 * i for i in range(16)])
    assert not result["passed"]
    assert result["status"] == "maximum_wait_reached"
    assert len(rows) == 16
    assert result["final_slope_c_per_minute"] > 0.2


def test_sensor_outage_is_distinct_from_zero(tmp_path):
    result, rows = acquire(tmp_path, [35.0, None])
    assert not result["passed"]
    assert result["status"] == "sensor_unavailable"
    assert result["final_temperature_c"] is None
    assert rows[-1]["temperature_c"] == ""


@pytest.mark.parametrize("temperature", [True, False, float("nan"), float("inf"), "35", 10**1000])
def test_invalid_sensor_values_cannot_pass_a_gate(tmp_path, temperature):
    result, rows = acquire(tmp_path, [temperature])
    assert not result["passed"]
    assert result["status"] == "sensor_unavailable"
    assert rows[-1]["temperature_c"] == ""


@pytest.mark.parametrize("baseline", [True, float("nan"), "35", 10**1000])
def test_invalid_baseline_rejected_before_raw_creation(tmp_path, baseline):
    with pytest.raises(ValueError, match="baseline must be finite"):
        acquire_thermal_condition(policy(), tmp_path / "trace.csv", baseline_c=baseline)
    assert not (tmp_path / "trace.csv").exists()


def test_firmware_stress_has_no_software_ceiling_but_requires_sensor():
    assert thermal_safety_reason(85., None, True) is None
    assert thermal_safety_reason(None, None, True)
    assert thermal_safety_reason(True, None, True)
    assert thermal_safety_reason(0., None, True) is None
    assert thermal_safety_reason(None, None, False) is None
    assert thermal_safety_reason(None, 80., False)
    assert thermal_safety_reason(80., 80., False)


def test_idle_baseline_is_measured_and_retained(tmp_path):
    result, rows = acquire(tmp_path, [33, 34, 35, 35, 36, 37], baseline=None)
    assert result["passed"]
    assert result["baseline_c"] == 35
    assert result["status"] == "baseline_acquired"
    assert len(rows) == 6


def test_acquisition_gaps_cannot_establish_stability(tmp_path):
    clock = ReplayClock()

    def delayed_sleep(seconds):
        clock.now += seconds + 4

    result = acquire_thermal_condition(
        policy(), tmp_path / "trace.csv", baseline_c=35,
        sensor=lambda: 35, clock=clock.clock, sleep=delayed_sleep,
    )
    assert not result["passed"]
    assert result["status"] == "maximum_wait_reached"


def test_slope_uses_monotonic_differences_and_exact_units():
    assert temperature_slope([(1e9, 35), (1e9 + 60, 36)]) == pytest.approx(1.0)
    assert temperature_slope([(0, 35)]) is None


@pytest.mark.parametrize("ticks", [
    [0., 0., -1.], [10., 10., 9.], [0., 0., float("nan")],
    [0., 0., float("inf")], [0., True], ["invalid", 0.], [10**1000, 0.],
])
def test_bad_protocol_clock_fails_closed_and_preserves_trace_and_actual_cost(tmp_path, ticks):
    """Injected monotonic faults cannot pass a gate or fabricate elapsed time."""

    clock = iter(ticks)
    result = acquire_thermal_condition(policy(), tmp_path / "trace.csv", baseline_c=35.,
                                     sensor=lambda: 35., clock=lambda: next(clock), sleep=lambda _: None)
    assert not result["passed"] and result["status"] == "clock_invalid"
    assert result["elapsed_seconds"] is None
    assert result["acquisition_cost"]["wall_seconds"] >= 0
    with gzip.open(result["trace_path"], "rt") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[-1]["status"] == "clock_invalid"
    assert rows[-1]["clock_error"] and rows[-1]["raw_clock_repr"]
    assert rows[-1]["monotonic_seconds"] == ""


@pytest.mark.parametrize("overrides", [
    {"stable_seconds": float("nan")}, {"tolerance_c": 0},
    {"timeout_seconds": 2}, {"sample_interval_seconds": 6},
    {"baseline_seconds": True},
    {"baseline_seconds": 10**1000},
])
def test_impossible_protocol_rejected_before_acquisition(overrides):
    with pytest.raises(ValueError):
        policy(**overrides)
