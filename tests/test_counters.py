import pytest

from pcsuchai.counters import matched_ipc, parse_counter_records


def parse(tmp_path, text, **options):
    path = tmp_path / "perf.csv"
    path.write_text(text)
    return parse_counter_records(path, **options)


def test_large_counts_keep_integer_precision_and_multiplexing(tmp_path):
    raw_count = 2**53 + 1
    report = parse(tmp_path, f"{raw_count};;cycles:u;1000000000;50.00;;\n")
    event = report["events"][0]
    assert event["reported_value"] == raw_count
    assert isinstance(event["reported_value"], int)
    assert event["quality"] == "poor_coverage"
    assert event["running_time_ns"] == 1_000_000_000
    assert event["enabled_time_ns_estimate"] == 2_000_000_000
    assert event["enabled_time_ns_rounding_bounds"][0] < 2_000_000_000 < event["enabled_time_ns_rounding_bounds"][1]


def test_unavailable_events_do_not_become_zero(tmp_path):
    report = parse(tmp_path, "<not supported>;;cycles:u;0;0\n<not counted>;;instructions:u;0;0\n0;;page-faults:u;100;100.00\n")
    unsupported, not_counted, zero = report["events"]
    assert unsupported["availability"] == "unsupported"
    assert unsupported["reported_value"] is None
    assert not_counted["availability"] == "not_counted"
    assert zero["availability"] == "available" and zero["reported_value"] == 0


def test_legacy_scaled_values_are_not_scaled_twice(tmp_path):
    report = parse(tmp_path, "100;;cycles;100;50.00\n", no_scale=False)
    assert report["events"][0]["scaled_value_estimate"] == 100
    assert report["events"][0]["reported_value_scaled_by_perf"]


def test_ipc_requires_same_scope_group_and_accounting_window(tmp_path):
    report = parse(tmp_path, "100;;cycles:u;1000;100.00\n200;;instructions:u;1000;100.00\n")
    assert matched_ipc(report, simultaneous_group=True)["value"] == 2
    assert matched_ipc(report, simultaneous_group=False)["value"] is None
    report["events"][1]["scope"] = "kernel"
    assert "scopes" in matched_ipc(report, simultaneous_group=True)["reason"]
    report["events"][1]["scope"] = "user"
    report["events"][1]["running_time_ns"] = 999
    assert matched_ipc(report, simultaneous_group=True)["value"] is None


def test_poor_coverage_cannot_produce_ipc(tmp_path):
    report = parse(tmp_path, "100;;cycles:u;1000;50.00\n200;;instructions:u;1000;50.00\n")
    assert matched_ipc(report, simultaneous_group=True)["value"] is None


def test_unparsed_lines_and_extra_fields_are_retained(tmp_path):
    report = parse(tmp_path, "# comment\n100;;cycles;1000;100.00;2.1;metric\nunrecognized\n")
    assert report["events"][0]["extra_fields"] == ["2.1", "metric"]
    assert report["unparsed_lines"][0]["raw_line"] == "unrecognized"


@pytest.mark.parametrize("coverage", [0, 101, float("nan")])
def test_invalid_coverage_contract_is_rejected(tmp_path, coverage):
    with pytest.raises(ValueError):
        parse(tmp_path, "", minimum_coverage_percent=coverage)
