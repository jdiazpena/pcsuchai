"""Synthetic scaling/control arithmetic; native product integration separately."""

import gzip
import json

import pytest

from pcsuchai.scaling_report import report_scaling


def job(size=100, profile="minimal", *, number=1, rows=None, status="complete", issues=None, kind="measured"):
    """Create an explicitly synthetic scaling observation, never target proof."""

    return {"experiment_id": "synthetic-e", "session_id": "synthetic-e:s1", "run_id": f"synthetic-{number}",
            "block_path": f"session1/block-{number}", "device_label": "synthetic-board", "pair": "skyfield-apexpy",
            "cohort_id": f"synthetic-cohort-{size}-{profile}", "kind": kind, "status": status, "issues": issues or [],
            "worker_seconds": 2., "full_cycle_seconds": 3.,
            "controls": {"kind": "scaling", "source_sha256": "synthetic-source", "python_version": "synthetic-python",
                         "packages": {"apexpy": "synthetic-v"}, "selection": {"method": "spread", "size": size},
                         "plot_profile": {"name": profile, "input_sha256": profile},
                         "inputs": {"measurements": {"sha256": "synthetic-data"}, "plot:archive-full": {"sha256": "synthetic-plots"}},
                         "execution": {"threads": "one", "process_mode": "fresh"}, "thermal": {"mode": "synthetic_replay"},
                         "observation": {"levels": ["normal"]}},
            "products": {"workload_details": {"observed_rows": rows if rows is not None else size,
                                               "selection": {"duplicate_timestamps": 2},
                                               "plot_products": [{"name": "particle_map", "format": "png", "width_px": 1200,
                                                                  "height_px": 600, "size_bytes": 400, "points_rendered": size,
                                                                  "data_status": "available", "rendering": {"filled_markers": True}}]}},
            "stages": [{"stage": "orbit", "process_cpu_seconds": 0.1, "peak_rss_bytes": 10000,
                        "read_bytes": 0, "write_bytes": 100, "read_chars": 200, "write_chars": 300}],
            "storage": {"logical_product_bytes": 1000, "new_content_bytes": 500}}


def report(tmp_path, jobs):
    """Write test-owned raw attempts and read the saved-only analysis."""

    journal = tmp_path / "attempts.jsonl.gz"
    with gzip.open(journal, "xt") as output:
        for item in jobs:
            output.write(json.dumps(item) + "\n")
    destination = tmp_path / "report"
    destination.mkdir()
    return report_scaling(journal, destination, resamples=100)


def test_size_scaling_full_chain_costs_units_and_exact_failed_denominator(tmp_path):
    small, big = job(), job(1000, number=2)
    big["worker_seconds"] = 8
    failed = job(number=3, status="failed")
    failed["products"] = None
    result = report(tmp_path, [small, big, failed])
    assert len(result["groups"]) == 1
    variants = result["groups"][0]["variants"]
    assert len(variants) == 2
    first = next(v for v in variants if v["variant"]["requested_size"] == 100)
    assert first["counts"]["measured_started"] == 2
    assert first["counts"]["usable_measured"] == 1
    assert first["counts"]["failed_or_interrupted"] == 1
    assert first["latency"]["worker_seconds_per_input_row"]["attempt_median"] == .02
    assert first["latency"]["worker_seconds_per_input_row"]["unit"] == "seconds_per_input_row"
    assert first["resources"]["read_bytes"]["minimum"] == 0
    ratios = result["groups"][0]["workload_cost_ratios"]
    assert next(r for r in ratios if r["metric"] == "worker_seconds")["ratio"] == .25
    assert ratios[0]["intended_variable"] == "input_size"
    assert ratios[0]["uncertainty"]["status"] == "unavailable"
    with gzip.open(tmp_path / "report/scaling.jsonl.gz", "rt") as journal:
        points = [json.loads(line) for line in journal]
    assert len(points) == 3 and points[-1]["actual_rows"] is None
    assert points[0]["selection"]["duplicate_timestamps"] == 2


def test_plot_scaling_retains_empty_filters_and_all_plot_metadata(tmp_path):
    minimal, full = job(), job(profile="archive-full", number=2)
    empty = {"name": "night_time", "format": "png", "size_bytes": 250, "points_rendered": 0,
             "data_status": "empty_selection", "width_px": 1800, "height_px": 800,
             "spec": {"exclude_time_ranges": [["synthetic-start", "synthetic-end"]], "day_night": "night"}}
    full["products"]["workload_details"]["plot_products"].append(empty)
    result = report(tmp_path, [minimal, full])
    variants = result["groups"][0]["variants"]
    bigger = next(v for v in variants if v["variant"]["plot_profile"]["name"] == "archive-full")
    assert bigger["resources"]["png_bytes"]["minimum"] == 650
    assert bigger["resources"]["plot_count"]["minimum"] == 2
    assert bigger["plot_contract_example"][-1] == empty
    assert result["groups"][0]["workload_cost_ratios"][0]["intended_variable"] == "plot_profile"


@pytest.mark.parametrize("change", ["source", "package", "thread", "process", "thermal", "backend", "device", "selection_method", "historical_data", "observation"])
def test_undeclared_controls_never_merge(tmp_path, change):
    first, second = job(), job(1000, number=2)
    control = second["controls"]
    if change == "source": control["source_sha256"] = "different"
    elif change == "package": control["packages"]["apexpy"] = "different"
    elif change == "thread": control["execution"]["threads"] = "stock"
    elif change == "process": control["execution"]["process_mode"] = "persistent"
    elif change == "thermal": control["thermal"]["mode"] = "different"
    elif change == "backend": second["pair"] = "skyfield-aacgmv2"
    elif change == "device": second["device_label"] = "different"
    elif change == "selection_method": control["selection"]["method"] = "prefix"
    elif change == "historical_data": control["inputs"]["measurements"]["sha256"] = "different"
    else: control["observation"]["levels"] = ["minimal"]
    assert len(report(tmp_path, [first, second])["groups"]) == 2


def test_changed_size_and_plot_not_conflated_into_one_cost_ratio(tmp_path):
    result = report(tmp_path, [job(), job(1000, profile="archive-full", number=2)])
    assert result["groups"][0]["workload_cost_ratios"] == []


def test_non_scaling_jobs_are_not_rebranded_as_scaling(tmp_path):
    item = job()
    item["controls"]["kind"] = "acceptance"
    assert report(tmp_path, [item])["groups"] == []


def test_missing_rows_or_stage_metrics_never_inferred_from_requested_work(tmp_path):
    item = job(size=None)
    item["products"]["workload_details"]["observed_rows"] = None
    item["stages"] = []
    result = report(tmp_path, [item])
    variant = result["groups"][0]["variants"][0]
    assert variant["counts"]["usable_measured"] == 0
    assert variant["actual_row_counts"] == []
    assert variant["latency"]["worker_seconds"]["attempt_count"] == 0
    assert variant["resources"]["sampled_peak_rss_bytes"]["minimum"] is None


def test_size_ratio_refuses_changed_rendering_despite_reused_profile_name(tmp_path):
    first, second = job(), job(1000, number=2)
    second["products"]["workload_details"]["plot_products"][0]["width_px"] = 2000
    result = report(tmp_path, [first, second])
    assert result["groups"][0]["workload_cost_ratios"][0]["status"] == "unavailable"


def test_disjoint_sessions_cannot_supply_paired_uncertainty(tmp_path):
    first, second = job(), job(1000, number=2)
    second["session_id"] = "synthetic-e:s2"
    result = report(tmp_path, [first, second])
    assert result["groups"][0]["workload_cost_ratios"][0]["status"] == "unavailable"


def test_timeline_and_centroid_dynamic_results_do_not_split_plot_contract(tmp_path):
    first, second = job(), job(1000, number=2)
    for index, item in enumerate((first, second)):
        p = item["products"]["workload_details"]["plot_products"][0]
        p.update(first_time_utc=f"synthetic-{index}", last_time_utc=f"synthetic-end-{index}",
                 particle_weighted_centroid={"latitude_deg": index})
    result = report(tmp_path, [first, second])
    assert result["groups"][0]["workload_cost_ratios"][0]["status"] == "available"


def test_native_scaling_chart_readable_and_unknown_rows_not_x_zero(tmp_path):
    from PIL import Image
    from pcsuchai.scaling_plotting import render_scaling_plots
    first, second, unknown = job(), job(1000, number=2), job(size=None, number=3)
    unknown["products"]["workload_details"]["observed_rows"] = None
    result = report(tmp_path, [first, second, unknown])
    plots = render_scaling_plots(result, tmp_path / "report")
    assert len(plots) == 1
    with Image.open(tmp_path / "report" / plots[0]["path"]) as image:
        image.load()
        assert image.format == "PNG" and image.size == (1200, 900)
    assert result["groups"][0]["variants"][-1]["counts"]["usable_measured"] == 0


def test_unknown_only_scaling_has_no_fake_curve(tmp_path):
    from pcsuchai.scaling_plotting import render_scaling_plots
    unknown = job(size=None)
    unknown["products"] = None
    assert render_scaling_plots(report(tmp_path, [unknown]), tmp_path / "report") == []
