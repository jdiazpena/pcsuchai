"""Synthetic exact counters/stage deltas; native integration is tested elsewhere."""

import base64
import gzip
import json

import pytest

from pcsuchai.resource_report import report_resources


def attempt(tmp_path, number=1, *, status="complete", kind="measured", issues=None):
    """Create an explicitly synthetic job with frozen counter controls."""

    directory = tmp_path / f"run-{number}"
    directory.mkdir()
    return {"experiment_id": "synthetic-e", "run_id": f"run-{number}", "session_id": "synthetic-e:s1",
            "cohort_id": "synthetic-cohort", "device_label": "synthetic-board", "pair": "astropy-apexpy",
            "kind": kind, "status": status, "issues": issues or [], "directory": str(directory),
            "controls": {"observation": {"counter_groups": [["cycles:u", "instructions:u"]], "minimum_counter_coverage_percent": 95}},
            "hardware_counters": {"status": "acceptable", "ipc": {"value": 999999}}}


def report(tmp_path, attempts, rows=()):
    """Write test-owned gzip journals and invoke the saved-only reader."""

    stages = tmp_path / "stages.jsonl.gz"
    with gzip.open(stages, "xt") as source:
        for job, stage in rows:
            source.write(json.dumps({"experiment_id": job["experiment_id"], "run_id": job["run_id"], "stage_record": stage}) + "\n")
    destination = tmp_path / "report"
    destination.mkdir()
    return report_resources(stages, attempts, destination)


def raw(job, text):
    """Store synthetic perf text, preserving every source byte."""

    from pathlib import Path
    with gzip.open(Path(job["directory"]) / "perf-stat.csv.gz", "xb") as source:
        source.write(text)


def test_stage_zero_missing_boolean_negative_and_exact_integers(tmp_path):
    job = attempt(tmp_path)
    job["controls"] = {}
    job["hardware_counters"] = None
    large = 2**53 + 1
    result = report(tmp_path, [job], [(job, {"stage": "orbit", "read_bytes": 0, "write_bytes": large,
                                         "read_chars": None, "write_chars": True, "minor_page_faults": -1})])
    tables = {t["metric"]: t for t in result["stage_tables"]}
    assert tables["read_bytes"]["accepted_measured"]["minimum"] == 0
    assert tables["write_bytes"]["observed"]["sum"] == large
    assert tables["write_bytes"]["observed"]["median_exact"] == {"numerator": str(large), "denominator": "1"}
    assert tables["read_chars"]["availability"] == {"unavailable": 1}
    assert tables["write_chars"]["availability"] == {"invalid_saved_value": 1}
    assert tables["minor_page_faults"]["availability"] == {"invalid_saved_value": 1}


def test_raw_counter_reparse_ignores_fabricated_recorded_ipc(tmp_path):
    job = attempt(tmp_path)
    large = 2**53 + 1
    text = f"{large};;cycles:u;1000;100.00\n{2*large};;instructions:u;1000;100.00\n".encode()
    raw(job, text)
    result = report(tmp_path, [job])
    assert result["counter_attempts"][0]["ipc"]["value"] == 2
    assert result["counter_tables"][0]["accepted_measured_reported_values"]["sum"] == large
    with gzip.open(tmp_path / "report/hardware-counters.jsonl.gz", "rt") as source:
        point = json.loads(source.readline())
    assert base64.b64decode(point["raw_bytes_base64"]) == text
    assert point["recorded_metadata"]["ipc"]["value"] == 999999
    assert point["accounting"]["events"][0]["enabled_time_ns_rounding_bounds"]


@pytest.mark.parametrize("status,kind,issues", [("failed", "measured", []), ("interrupted", "measured", []),
                                               ("complete", "warmup", []), ("complete", "measured", ["science disagreement"])])
def test_outcomes_remain_observed_but_not_accepted_stats(tmp_path, status, kind, issues):
    job = attempt(tmp_path, status=status, kind=kind, issues=issues)
    raw(job, b"100;;cycles:u;1000;100.00\n200;;instructions:u;1000;100.00\n")
    result = report(tmp_path, [job], [(job, {"stage": "orbit", "read_bytes": 0})])
    assert result["counter_tables"][0]["observed_reported_values"]["available_count"] == 1
    assert result["counter_tables"][0]["accepted_measured_reported_values"]["available_count"] == 0
    assert result["stage_tables"][0]["observed"]["available_count"] == 1
    assert result["stage_tables"][0]["accepted_measured"]["available_count"] == 0


def test_denied_missing_counter_no_fake_values(tmp_path):
    job = attempt(tmp_path)
    job["hardware_counters"] = {"status": "not_collected", "reason": "permission denied"}
    result = report(tmp_path, [job])
    assert result["counter_attempts"][0]["collection_status"] == "unavailable"
    assert result["counter_attempts"][0]["reason"] == "permission denied"
    assert result["counter_attempts"][0]["ipc"]["value"] is None
    assert result["counter_tables"][0]["availability"] == {"unavailable": 1}
    assert result["counter_tables"][0]["observed_reported_values"]["sum"] is None
    assert result["stage_attempts"][0]["availability"] == "unavailable_no_saved_stages"


@pytest.mark.parametrize("text", [b"100;;cycles:u;1000;50.00\n200;;instructions:u;1000;50.00\n",
                                 b"100;;cycles:u;1000;100.00\n200;;instructions:k;1000;100.00\n",
                                 b"100;;cycles:u;1000;100.00\n200;;instructions:u;1001;100.00\n",
                                 b"<not supported>;;cycles:u;0;0\n<not counted>;;instructions:u;0;0\n"])
def test_poor_scope_window_or_unavailable_cannot_supply_ipc(tmp_path, text):
    job = attempt(tmp_path)
    raw(job, text)
    result = report(tmp_path, [job])
    assert result["counter_attempts"][0]["ipc"]["value"] is None


def test_malformed_counter_lines_retained_and_not_accepted(tmp_path):
    job = attempt(tmp_path)
    text = b"100;;cycles:u;1000;100.00\n200;;instructions:u;1000;100.00\nmalformed\xff\n"
    raw(job, text)
    result = report(tmp_path, [job])
    assert result["counter_attempts"][0]["collection_status"] == "unavailable_or_poor_coverage"
    assert result["counter_attempts"][0]["ipc"]["value"] is None
    assert result["counter_tables"][0]["accepted_measured_reported_values"]["available_count"] == 0
    with gzip.open(tmp_path / "report/hardware-counters.jsonl.gz", "rt") as source:
        assert base64.b64decode(json.loads(source.readline())["raw_bytes_base64"]) == text


def test_counter_symlink_refused_without_external_read(tmp_path):
    from pathlib import Path
    job = attempt(tmp_path)
    external = tmp_path / "outside.csv"
    external.write_bytes(b"private external bytes")
    (Path(job["directory"]) / "perf-stat.csv").symlink_to(external)
    result = report(tmp_path, [job])
    assert result["counter_attempts"][0]["collection_status"] == "invalid_saved_counter_evidence"
    assert result["issues"]
    with gzip.open(tmp_path / "report/hardware-counters.jsonl.gz", "rt") as source:
        assert json.loads(source.readline())["raw_bytes_base64"] is None


def test_missing_requested_event_retains_unavailable_slot(tmp_path):
    job = attempt(tmp_path)
    raw(job, b"100;;cycles:u;1000;100.00\n")
    result = report(tmp_path, [job])
    assert result["counter_attempts"][0]["ipc"]["value"] is None
    assert any(t["availability"] == {"missing_requested_event": 1} for t in result["counter_tables"])
