from pcsuchai.report_plotting import DisplayEnvelope, outcome_series, reading_elapsed, render_report_plots


def test_display_is_bounded_and_extrema_endpoints_survive():
    envelope = DisplayEnvelope(maximum_bins=8)
    for index in range(10000):
        envelope.add(float(index), 1000000 if index == 4567 else -1000000 if index == 1234 else float(index % 7))
    points = envelope.points()
    assert len(points) <= 32
    assert points[0][0] == 0
    assert points[-1][0] == 9999
    assert max(point[1] for point in points) == 1000000
    assert min(point[1] for point in points) == -1000000
    assert envelope.metadata()["raw_numeric_samples"] == 10000
    assert envelope.metadata()["raw_samples_deleted"] is False


def test_display_does_not_sort_clock_adjustment_into_false_sequence():
    envelope = DisplayEnvelope()
    envelope.add(2, 20)
    envelope.add(1, 10)
    assert [point[0] for point in envelope.points()] == [2, 1]


def test_acquisition_clock_and_historical_context_are_distinguished():
    reading = {"monotonic_seconds": 112.0}
    elapsed, source = reading_elapsed(reading, {"elapsed_anchor_monotonic_seconds": "100", "campaign_elapsed_seconds": "15"})
    assert elapsed == 12 and source.startswith("individual_acquisition")
    elapsed, source = reading_elapsed(reading, {"campaign_elapsed_seconds": "15"})
    assert elapsed == 15 and source.startswith("historical_sample_context")
    assert reading_elapsed(reading, {"campaign_elapsed_seconds": "nan"}) == (None, "unavailable")
    assert reading_elapsed({"monotonic_seconds": True}, {"elapsed_anchor_monotonic_seconds": "100"}) == (None, "unavailable")


def test_pair_warmup_failure_and_excluded_outcomes_do_not_merge():
    base = {"attempt_number": 1, "worker_seconds": 2, "kind": "measured", "status": "complete", "issues": []}
    attempts = [{**base, "pair": "astropy-apexpy"}, {**base, "pair": "skyfield-apexpy"},
                {**base, "pair": "astropy-apexpy", "issues": ["science excluded"]},
                {**base, "pair": "astropy-apexpy", "kind": "warmup"},
                {**base, "pair": "astropy-apexpy", "status": "failed"}]
    groups = outcome_series(attempts)
    assert len(groups) == 5
    assert {group["status"] for group in groups} == {"complete", "excluded", "failed"}
    assert {group["kind"] for group in groups} == {"measured", "warmup"}


def test_readable_report_retains_pair_and_elapsed_source_metadata(tmp_path):
    import gzip
    import json
    from PIL import Image

    journal = tmp_path / "observations.jsonl.gz"
    with gzip.open(journal, "wt") as stream:
        stream.write(json.dumps({"experiment_id": "e", "block_path": "b", "raw_csv_fields": {
            "campaign_elapsed_seconds": "15", "elapsed_anchor_monotonic_seconds": "100"},
            "observations": {"board": {"soc_temperature_c": {"status": "available", "value": 42,
                                                               "monotonic_seconds": 112}}}}) + "\n")
    attempts = [{"experiment_id": "e", "block_path": "b", "pair": pair, "kind": "measured", "status": "complete",
                 "issues": [], "attempt_number": 1, "worker_seconds": 2} for pair in ("astropy-apexpy", "skyfield-apexpy")]
    result = render_report_plots(journal, attempts, tmp_path)[0]
    assert len(result["outcome_groups"]) == 2
    assert result["elapsed_sources"] == ["individual_acquisition_monotonic_minus_retained_segment_anchor"]
    with Image.open(tmp_path / result["path"]) as image:
        image.load()
        assert image.size == (1100, 900)
