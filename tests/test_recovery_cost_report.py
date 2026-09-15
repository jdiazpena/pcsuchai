"""Synthetic thermal traces/clocks; real compression/hash/receipt operations."""

import base64
import gzip
import json

import pytest

from pcsuchai.recovery_cost_report import report_recovery_costs
from pcsuchai.thermal import ThermalPolicy, acquire_thermal_condition


def experiment(tmp_path):
    """Make a test-owned trace tree, explicitly not a Pi acceptance campaign."""

    root = tmp_path / "synthetic-experiment"
    path = root / "sessions/session-0001/block-0001/recovery/trace.csv"
    return {"root": root, "identity": "synthetic-e", "state": {"device_label": "synthetic-board"}}, path


def acquire(path, temperature=35.):
    """Replay a two-second protocol; actual call costs use real clock/CPU."""

    ticks = iter([0., 0., 1., 2., 2.])
    return acquire_thermal_condition(ThermalPolicy(baseline_seconds=2, stable_seconds=2, timeout_seconds=3,
                                                  sample_interval_seconds=1), path, baseline_c=35.,
                                     sensor=lambda: temperature, clock=lambda: next(ticks, 2.), sleep=lambda _: None)


def report(tmp_path, value):
    """Read the saved trace tree without running a sensor or thermal gate."""

    destination = tmp_path / "report"
    destination.mkdir()
    return report_recovery_costs([value], destination)


def test_receipt_binds_trace_and_costs_do_not_use_injected_protocol_time(tmp_path):
    value, path = experiment(tmp_path)
    result = acquire(path)
    assert result["elapsed_seconds"] == 2.
    cost = result["acquisition_cost"]
    assert cost["wall_seconds"] >= 0 and cost["parent_process_cpu_seconds"] >= 0
    assert cost["wall_seconds"] == pytest.approx(cost["ended"]["monotonic_seconds"] - cost["started"]["monotonic_seconds"])
    saved = report(tmp_path, value)
    group = saved["experiments"][0]
    assert group["status"] == "available" and group["trace_count"] == 1
    assert group["passed_conditions"] == 1
    assert group["total_acquisition_wall_seconds"] == cost["wall_seconds"]


def test_unmet_condition_has_recorded_cost_not_fake_success(tmp_path):
    value, path = experiment(tmp_path)
    result = acquire(path, temperature=None)
    saved = report(tmp_path, value)["experiments"][0]
    assert not result["passed"] and saved["unmet_conditions"] == 1
    assert saved["status"] == "available"
    assert saved["total_acquisition_wall_seconds"] is not None


def test_missing_legacy_receipt_is_unavailable_not_trace_timestamp_estimate(tmp_path):
    value, path = experiment(tmp_path)
    path.parent.mkdir(parents=True)
    with gzip.open(path.with_name(path.name + ".gz"), "wt") as trace:
        trace.write("elapsed_seconds,temperature_c\n0,35\n60,35\n")
    saved = report(tmp_path, value)["experiments"][0]
    assert saved["trace_count"] == 1 and saved["available_cost_count"] == 0
    assert saved["total_acquisition_wall_seconds"] is None


@pytest.mark.parametrize("change", ["hash", "clock", "boolean", "outcome", "unknown_outcome", "scope", "source", "units"])
def test_bad_receipts_rejected_and_original_bytes_retained(tmp_path, change):
    from pathlib import Path
    value, path = experiment(tmp_path)
    result = acquire(path)
    receipt_path = Path(result["cost_receipt"])
    cost = json.loads(receipt_path.read_text())
    if change == "hash": cost["trace_sha256"] = "0" * 64
    elif change == "clock": cost["wall_seconds"] += 1
    elif change == "boolean": cost["wall_seconds"] = True
    elif change == "outcome": cost["passed"] = False
    elif change == "unknown_outcome":
        cost["result_status"], cost["passed"] = "invented", False
    else: cost[change] = "incorrect"
    receipt_path.write_text(json.dumps(cost))
    raw = receipt_path.read_bytes()
    saved = report(tmp_path, value)
    assert saved["issues"]
    assert saved["experiments"][0]["total_acquisition_wall_seconds"] is None
    with gzip.open(tmp_path / "report/recovery-costs.jsonl.gz", "rt") as journal:
        assert base64.b64decode(json.loads(journal.readline())["raw_receipt_base64"]) == raw
    assert receipt_path.read_bytes() == raw


def test_closed_gzip_preferred_without_double_counting_or_deleting_plain(tmp_path):
    value, path = experiment(tmp_path)
    result = acquire(path)
    with gzip.open(result["trace_path"], "rb") as trace:
        path.write_bytes(trace.read())
    assert report(tmp_path, value)["experiments"][0]["trace_count"] == 1
    assert path.exists()


def test_no_acquisitions_does_not_claim_zero_cost(tmp_path):
    value, _path = experiment(tmp_path)
    saved = report(tmp_path, value)["experiments"][0]
    assert saved["status"] == "no_saved_recovery_acquisitions"
    assert saved["total_acquisition_wall_seconds"] is None


def test_linked_receipt_refused_without_reading_external_bytes(tmp_path):
    from pathlib import Path
    value, path = experiment(tmp_path)
    result = acquire(path)
    receipt = Path(result["cost_receipt"])
    receipt.unlink()  # Only this test-owned metadata is replaced by a fault.
    external = tmp_path / "outside"
    external.write_bytes(b"external bytes")
    receipt.symlink_to(external)
    saved = report(tmp_path, value)
    assert saved["issues"]
    with gzip.open(tmp_path / "report/recovery-costs.jsonl.gz", "rt") as journal:
        assert json.loads(journal.readline())["raw_receipt_base64"] is None
