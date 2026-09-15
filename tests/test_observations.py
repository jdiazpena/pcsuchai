import json
import os
from pathlib import Path

import pytest

import pcsuchai.observations as observations


def test_zero_is_available_and_missing_is_not_zero():
    zero = observations.measurement(0, unit="count", scope="worker", source="test")
    missing = observations.measurement(None, unit="count", scope="worker", source="test", status="denied", reason="permission")
    assert zero["status"] == "available" and zero["value"] == 0
    assert missing["status"] == "denied" and missing["value"] is None
    assert zero["captured_utc"] and zero["monotonic_seconds"] > 0


def test_kernel_high_water_is_lifetime_bytes_not_sampled_peak(tmp_path):
    process = tmp_path / "123"
    process.mkdir()
    (process / "status").write_text("Name:\tworker\nVmHWM:\t1234 kB\n")
    reading = observations.read_process_high_water(123, tmp_path)
    assert reading["value"] == 1234 * 1024
    assert reading["unit"] == "bytes"
    assert reading["source"].endswith(":VmHWM")


def test_absent_or_malformed_kernel_fields_keep_the_reason(tmp_path):
    absent = observations.read_process_high_water(123, tmp_path)
    assert absent["status"] == "unsupported" and absent["value"] is None
    process = tmp_path / "123"
    process.mkdir()
    (process / "status").write_text("VmHWM:\t1234 bananas\n")
    malformed = observations.read_process_high_water(123, tmp_path)
    assert malformed["status"] == "unavailable"
    assert "unit" in malformed["reason"]


def test_pressure_preserves_raw_categories_and_units(tmp_path):
    pressure = tmp_path / "memory"
    pressure.write_text("some avg10=1.25 avg60=0.40 avg300=0.10 total=123456\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
    reading = observations.read_pressure(pressure)
    assert reading["value"]["some"]["total_microseconds"] == 123456
    assert reading["value"]["full"]["total_microseconds"] == 0
    assert reading["value"]["some"]["avg10_percent"] == 1.25


def test_actual_process_resources_have_individual_availability():
    readings = observations.process_measurements(os.getpid(), scope="supervisor", native_memory=True)
    assert readings["rss_bytes"]["value"] > 0
    for reading in readings.values():
        assert reading["scope"] == "supervisor"
        assert {"unit", "status", "source", "captured_utc", "monotonic_seconds"} <= reading.keys()
    assert readings["pss_bytes"]["status"] in ("available", "unsupported", "denied", "unavailable")


def test_native_memory_not_sampled_is_not_filled_with_previous_value():
    readings = observations.process_measurements(os.getpid(), scope="worker", native_memory=False)
    assert readings["pss_bytes"]["status"] == "not_sampled"
    assert readings["pss_bytes"]["value"] is None


def test_firmware_clock_has_its_own_availability(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("vcgencmd")

    monkeypatch.setattr(observations.subprocess, "run", missing)
    reading = observations.firmware_arm_clock()
    assert reading["value"] is None
    assert reading["status"] == "unsupported"
    assert reading["unit"] == "Hz"


def test_sampler_retains_only_latest_cpu_totals_per_scope(tmp_path, monkeypatch):
    def fake_process(pid, *, scope, native_memory):
        return {
            "cpu_user_seconds": observations.measurement(1, unit="seconds", scope=scope, source="fixture"),
            "cpu_system_seconds": observations.measurement(0, unit="seconds", scope=scope, source="fixture"),
        }

    monkeypatch.setattr(observations, "process_measurements", fake_process)
    sampler = observations.ObservationSampler()
    for pid in range(1, 101):
        result = sampler.capture(tmp_path, worker_pid=pid)
    assert len(sampler.previous_cpu) == 2
    assert result["worker"]["cpu_equivalent_percent"]["status"] == "initializing"


def test_raw_sampler_json_preserves_scopes_and_unavailable_clock(tmp_path):
    raw = json.loads(observations.ObservationSampler().capture_json(tmp_path))
    assert raw["supervisor"]["rss_bytes"]["value"] > 0
    assert "requested_frequency_hz" in raw["board"]
    assert "observed_firmware_arm_frequency_hz" in raw["board"]
    assert raw["board"]["free_bytes"]["value"] >= 0


def test_journal_retains_elapsed_anchor_across_resume_offset(tmp_path, monkeypatch):
    import csv
    import pcsuchai.benchmark_suite as suite

    monkeypatch.setattr(suite, "_telemetry_snapshot", lambda _path: {})
    journal = suite._TelemetryJournal(tmp_path / "raw.csv", tmp_path, 2, elapsed_offset=30)
    monkeypatch.setattr(journal.observations, "capture_json", lambda *args, **kwargs: "{}")
    record = journal.sample()
    assert record["elapsed_anchor_monotonic_seconds"] == journal.started - 30
    assert record["campaign_elapsed_seconds"] >= 30
    with (tmp_path / "raw.csv").open() as handle:
        row = next(csv.DictReader(handle))
    assert float(row["elapsed_anchor_monotonic_seconds"]) == journal.started - 30
    assert row["segment_id"] == journal.segment_id


def test_firmware_mask_zero_is_available_and_missing_command_unsupported(monkeypatch):
    import subprocess

    monkeypatch.setattr(observations.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "throttled=0x0\n", ""))
    result = observations.firmware_throttling()
    assert result["status"] == "available" and result["value"] == 0
    assert result["source"] == "vcgencmd get_throttled" and result["monotonic_seconds"] > 0

    def missing(*args, **kwargs):
        raise FileNotFoundError("vcgencmd")

    monkeypatch.setattr(observations.subprocess, "run", missing)
    result = observations.firmware_throttling()
    assert result["value"] is None and result["status"] == "unsupported"


def test_firmware_mask_is_acquired_once_and_reused_in_raw_journal(tmp_path, monkeypatch):
    import csv
    import pcsuchai.benchmark_suite as suite
    calls = []

    def firmware():
        calls.append(1)
        return observations.measurement(4, unit="firmware_bitmask", scope="board", source="synthetic-firmware")

    monkeypatch.setattr(observations, "firmware_throttling", firmware)
    journal = suite._TelemetryJournal(tmp_path / "raw.csv", tmp_path, 2)
    row = journal.sample()
    assert calls == [1]
    assert row["throttled"] == "0x4"
    with (tmp_path / "raw.csv").open() as stream:
        readings = json.loads(next(csv.DictReader(stream))["observations_json"])
    assert readings["board"]["throttling_flags"]["value"] == 4


@pytest.mark.parametrize("output", ["throttled=-1", "clock=0x0", "throttled=0xZZ", "throttled=0x100000000"])
def test_malformed_firmware_mask_has_reason_not_zero(monkeypatch, output):
    import subprocess
    monkeypatch.setattr(observations.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""))
    result = observations.firmware_throttling()
    assert result["value"] is None and result["status"] == "unavailable"
    assert result["reason"]
