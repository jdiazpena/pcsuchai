"""Synthetic exact clocks and real fsynced journals; not performance evidence."""

import json

import pytest

import pcsuchai.campaign_costs as module
from pcsuchai.campaign_cost_report import report_campaign_costs


def test_phase_timer_and_total_do_not_double_count_child_spans(tmp_path, monkeypatch):
    clock = {"wall": 0., "cpu": 0.}
    def now():
        return {"captured_utc": "2026-09-15T00:00:00+00:00", "monotonic_seconds": clock["wall"], "process_cpu_seconds": clock["cpu"]}
    monkeypatch.setattr(module, "cost_clock", now)
    started = now()
    clock.update(wall=2., cpu=1.)
    costs = module.CampaignCosts(tmp_path, started)
    def block():
        clock.update(wall=12., cpu=3.)
        return "unchanged result"
    assert costs.call("block_execution", block) == "unchanged result"
    clock.update(wall=15., cpu=4.)
    total = costs.finish("complete")
    rows = [json.loads(line) for line in (tmp_path / "costs.jsonl").read_text().splitlines()]
    assert [row["wall_seconds"] for row in rows] == [2., 10.]
    assert rows[-1]["parent_process_cpu_seconds"] == 2.
    assert total["wall_seconds"] == 15.  # includes three seconds of unclassified overhead
    assert total["parent_process_cpu_seconds"] == 4.


def test_failed_and_interrupted_calls_preserve_phase_and_exception(tmp_path):
    costs = module.CampaignCosts(tmp_path, module.cost_clock())
    def failed():
        raise KeyboardInterrupt("stop")
    with pytest.raises(KeyboardInterrupt, match="stop"):
        costs.call("full_validation", failed)
    costs.finish("stopped")
    rows = [json.loads(line) for line in (tmp_path / "costs.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "failed"
    assert rows[-1]["error_type"] == "KeyboardInterrupt"
    assert rows[-1]["wall_seconds"] >= 0


def test_existing_journal_is_never_overwritten(tmp_path):
    costs = module.CampaignCosts(tmp_path, module.cost_clock())
    costs.finish("complete")
    original = (tmp_path / "costs.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        module.CampaignCosts(tmp_path, module.cost_clock())
    assert (tmp_path / "costs.jsonl").read_bytes() == original


def test_saved_costs_reconstruct_segment_without_warmup_or_failed_throughput(tmp_path):
    segment = tmp_path / "original/segments/one"
    segment.mkdir(parents=True)
    costs = module.CampaignCosts(segment, module.cost_clock())
    costs.call("block_execution", lambda: None)
    costs.finish("stopped")
    output = tmp_path / "report"
    output.mkdir()
    attempts = [{"experiment_id": "original", "kind": kind, "status": status, "issues": []}
                for kind, status in [("measured", "complete"), ("measured", "failed"), ("warmup", "complete")]]
    result = report_campaign_costs([{"identity": "original", "root": tmp_path / "original"}], attempts, output)
    saved = result["experiments"][0]
    assert saved["status"] == "available" and saved["valid_scheduled_jobs"] == 1
    assert saved["active_API_wall_seconds"] > 0
    assert saved["segments"][0]["unclassified_orchestration_wall_seconds"] >= 0


@pytest.mark.parametrize("line", [b'{"wall_seconds":NaN}\n', b'{"wall_seconds":1,"wall_seconds":2}\n', b'{"wall_seconds":1e999}\n', b'partial'])
def test_corrupt_partial_journal_is_preserved_without_throughput(tmp_path, line):
    import base64
    import gzip
    segment = tmp_path / "original/segments/one"
    segment.mkdir(parents=True)
    (segment / "costs.jsonl").write_bytes(line)
    output = tmp_path / "report"
    output.mkdir()
    result = report_campaign_costs([{"identity": "original", "root": tmp_path / "original"}], [], output)
    assert result["experiments"][0]["active_API_wall_seconds"] is None
    with gzip.open(output / "campaign-costs.jsonl.gz", "rt") as source:
        saved = json.loads(source.readline())
    assert base64.b64decode(saved["raw_line_base64"]) == line
    assert saved["parsed_phase"] is None
