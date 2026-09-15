"""Synthetic saved sensor/job replays, not measured Pi performance."""

import gzip
import json

import pytest

from pcsuchai.thermal_performance import Association, report_thermal_performance


def attempt(index, *, kind="measured", status="complete", pair="astropy-apexpy"):
    return dict(experiment_id="e", run_id=str(index), kind=kind, status=status, recorded_status=status,
                cohort_id=pair, device_label="synthetic", pair=pair, issues=[], session_id="e:s1", block_path="b",
                worker_seconds=float(index + 1), full_cycle_seconds=float(index + 2))


def journal(path, attempts, *, unavailable=False):
    with gzip.open(path, "wt") as handle:
        for index, item in enumerate(attempts):
            reading = dict(status="unsupported" if unavailable else "available", value=None if unavailable else 30.+index,
                           monotonic_seconds=1000.+index*400, source="synthetic SoC trace", unit="degrees_Celsius", scope="board_soc")
            row = dict(experiment_id="e", raw_csv_fields=dict(run_id=item["run_id"], phase=item["kind"],
                       campaign_elapsed_seconds=str(index*400), segment_id="seg"), observations=dict(board=dict(soc_temperature_c=reading)))
            handle.write(json.dumps(row)+"\n")


def test_association_exact_slope_and_constant_temperature_are_distinct():
    varying, constant = Association(), Association()
    for x in (30., 31., 32.):
        varying.add(x, 2*x+1)
        constant.add(30., x)
    assert varying.report()["slope_seconds_per_celsius"] == 2.
    assert varying.report()["pearson_r"] == 1.
    assert constant.report()["status"] == "unavailable"
    assert constant.report()["slope_seconds_per_celsius"] is None


def test_warmup_and_failure_remain_raw_but_are_not_measured_association(tmp_path):
    jobs = [attempt(0, kind="warmup"), attempt(1), attempt(2), attempt(3), attempt(4, status="failed")]
    source = tmp_path / "observations.gz"
    journal(source, jobs)
    result = report_thermal_performance(source, jobs, tmp_path, resamples=100)
    assert all(fit["jobs"] == 3 for fit in result["associations"])
    assert {phase["kind"] for phase in result["phase_latency"]} == {"warmup", "measured"}
    with gzip.open(tmp_path / "thermal-performance.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 5 and rows[-1]["status"] == "failed"
    assert rows[0]["usable_for_measured_association"] is False


def test_unavailable_sensor_never_becomes_zero_or_blocks_latency_phase_report(tmp_path):
    jobs = [attempt(0), attempt(1), attempt(2)]
    source = tmp_path / "observations.gz"
    journal(source, jobs, unavailable=True)
    result = report_thermal_performance(source, jobs, tmp_path, resamples=100)
    assert result["associations"] == []
    assert result["phase_latency"][0]["statistics"]["attempt_count"] == 3
    with gzip.open(tmp_path / "thermal-performance.jsonl.gz", "rt") as handle:
        assert all(json.loads(line)["sampled_temperature"]["mean"] is None for line in handle)


def test_early_late_windows_do_not_mix_backend_pairs_or_claim_stationarity(tmp_path):
    jobs = [attempt(index, pair="astropy-apexpy" if index % 2 else "skyfield-aacgmv2") for index in range(6)]
    source = tmp_path / "observations.gz"
    journal(source, jobs)
    result = report_thermal_performance(source, jobs, tmp_path, resamples=100)
    assert len(result["early_late_windows"]) == 2
    assert all(row["status"] == "descriptive_disjoint_context_windows" for row in result["early_late_windows"])
    for row in result["early_late_windows"]:
        assert row["metrics"]["worker_seconds"]["initial"]["session_count"] == 1
        assert row["metrics"]["worker_seconds"]["initial"]["uncertainty"]["status"] == "unavailable"


@pytest.mark.parametrize("window", [True, -1, 0, float("nan")])
def test_invalid_window_rejected_before_file_access(tmp_path, window):
    with pytest.raises(ValueError):
        report_thermal_performance(tmp_path/"missing", [], tmp_path, window_seconds=window)


def test_failed_late_job_is_counted_without_inflating_valid_late_latency(tmp_path):
    jobs = [attempt(0), attempt(1), attempt(2, status="failed")]
    source = tmp_path / "observations.gz"
    journal(source, jobs)
    result = report_thermal_performance(source, jobs, tmp_path, resamples=100)
    late = result["early_late_windows"][0]
    assert late["outcomes"]["late"]["failed_or_interrupted"] == 1
    assert late["metrics"]["worker_seconds"]["late"]["attempt_count"] == 0


@pytest.mark.parametrize("unavailable", [False, True])
def test_plot_is_readable_and_missing_sensor_is_not_drawn_as_zero(tmp_path, unavailable):
    from PIL import Image
    from pcsuchai.thermal_performance_plotting import render_thermal_performance_plots
    jobs = [attempt(0), attempt(1), attempt(2)]
    source = tmp_path / "observations.gz"
    journal(source, jobs, unavailable=unavailable)
    report_thermal_performance(source, jobs, tmp_path, resamples=100)
    plots = render_thermal_performance_plots(tmp_path / "thermal-performance.jsonl.gz", tmp_path)
    assert len(plots) == 1
    assert plots[0]["missing_temperature_contexts"] == (3 if unavailable else 0)
    with Image.open(tmp_path / plots[0]["path"]) as image:
        assert image.size == (1000, 500)
        image.verify()


@pytest.mark.parametrize("change", ["wrong_scope", "regressed_clock"])
def test_invalid_sensor_scope_or_clock_excludes_association_without_dropping_job(tmp_path, change):
    jobs = [attempt(0), attempt(1), attempt(2)]
    source = tmp_path / "observations.gz"
    journal(source, jobs)
    with gzip.open(source, "rt") as handle:
        rows = [json.loads(line) for line in handle]
    if change == "wrong_scope":
        for row in rows:
            row["observations"]["board"]["soc_temperature_c"]["scope"] = "external_sensor"
    else:
        rows = [entry for row in rows for entry in (row, json.loads(json.dumps(row)))]
        for index in range(1, len(rows), 2):
            rows[index]["observations"]["board"]["soc_temperature_c"]["monotonic_seconds"] -= 1
    with gzip.open(source, "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row)+"\n")
    result = report_thermal_performance(source, jobs, tmp_path, resamples=100)
    assert result["associations"] == []
    assert result["phase_latency"][0]["statistics"]["attempt_count"] == 3
