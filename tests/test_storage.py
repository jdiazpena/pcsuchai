"""Real local filesystem costs plus explicitly synthetic forecast arithmetic."""

import gzip
import json
import os
from pathlib import Path

import pytest

from pcsuchai.benchmark_suite import _retain_run
from pcsuchai.storage import filesystem_capacity, forecast_storage, inventory_storage
from pcsuchai.storage_report import report_storage
from pcsuchai.retention import deduplicate_products


def test_inventory_counts_hardlinks_once_and_does_not_enter_symlinks(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    first = root / "first"
    first.write_bytes(b"a" * 10000)
    os.link(first, root / "second")
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret").write_bytes(b"b" * 50000)
    (root / "external-link").symlink_to(external, target_is_directory=True)
    result = inventory_storage(root)
    assert result["logical_file_bytes"] == 20000
    assert result["file_names"] == 2
    assert result["unique_inodes"] == 2  # directory and one data inode
    assert result["symlinks_not_followed"] == 1
    assert result["unique_allocated_bytes"] == (root.stat().st_blocks + first.stat().st_blocks) * 512


def test_sparse_file_allocation_is_not_its_logical_length(tmp_path):
    path = tmp_path / "sparse"
    with path.open("wb") as handle:
        handle.truncate(100_000_000)
    result = inventory_storage(path)
    assert result["logical_file_bytes"] == 100_000_000
    assert result["unique_allocated_bytes"] == path.stat().st_blocks * 512


def test_symbolic_link_root_is_not_traversed(tmp_path):
    directory = tmp_path / "external"
    directory.mkdir()
    (directory / "file").write_bytes(b"outside")
    link = tmp_path / "link"
    link.symlink_to(directory, target_is_directory=True)
    result = inventory_storage(link)
    assert result["logical_file_bytes"] == 0
    assert result["symlinks_not_followed"] == 1


def test_link_failure_records_real_blocks_and_keeps_all_bytes(tmp_path, monkeypatch):
    products = tmp_path / "products"
    products.mkdir()
    path = products / "data"
    path.write_bytes(b"keep all of this")
    def unsupported(*args, **kwargs):
        raise OSError("hard links unavailable")
    monkeypatch.setattr(os, "link", unsupported)
    result = deduplicate_products(products, tmp_path / "store")
    assert result["fallback_files"] == result["new_product_inodes"] == 1
    assert result["new_product_allocated_bytes"] == path.stat().st_blocks * 512
    assert path.read_bytes() == b"keep all of this"


def test_retention_measures_verified_compression_and_shared_file_blocks(tmp_path):
    destination = tmp_path / "campaign"
    destination.mkdir()
    before = filesystem_capacity(destination)
    saved = []
    for name in ("one", "two"):
        run = destination / name
        products = run / "products"
        products.mkdir(parents=True)
        (run / "attempt-intent.json").write_text(json.dumps({"capacity_before_attempt": before}))
        (run / "stdout.log").write_bytes(b"abc\n" * 1000)
        (products / "plot.png").write_bytes(b"same scientific bytes" * 1000)
        saved.append(_retain_run(run, destination))
    first, second = saved
    assert second["shared_files"] == 1
    assert second["new_product_allocated_bytes"] == 0
    assert first["new_product_allocated_bytes"] > 0
    assert second["new_retained_file_allocated_bytes"] > 0  # unique logs/intent still saved
    record = second["compression_records"][0]
    assert record["original_bytes"] == 4000
    assert record["compressed_bytes"] == Path(record["path"]).stat().st_size
    assert record["compressed_to_original_ratio"] < 1
    assert gzip.decompress(Path(record["path"]).read_bytes()) == b"abc\n" * 1000
    assert second["retention_wall_seconds"] >= second["compression_wall_seconds"] + second["sharing_wall_seconds"]
    assert second["capacity_before_attempt"] == before
    assert second["observed_filesystem_growth_bytes"] == before["free_bytes"] - second["capacity_after_retention"]["free_bytes"]


def test_capacity_failure_is_not_zero(monkeypatch, tmp_path):
    def denied(path):
        raise PermissionError("denied")
    monkeypatch.setattr(os, "statvfs", denied)
    result = filesystem_capacity(tmp_path)
    assert result["status"] == "unavailable"
    assert result["free_bytes"] is None


def test_forecast_uses_worst_observed_job_and_both_resource_limits():
    capacity = {"status": "available", "free_bytes": 10000, "free_inodes": 10}
    result = forecast_storage([100, 200], [1, 2], capacity, planned_attempts=6, reserve_bytes=1000)
    assert result["conditional_attempt_capacity"] == 5  # inodes, not bytes, limit this pilot
    assert result["planned_growth_bytes"] == 1200
    assert result["fits_observed_capacity"] is False
    assert result["guaranteed_to_fit"] is False


@pytest.mark.parametrize("growth,inodes,capacity,reserve", [
    ([0], [1], {"status": "available", "free_bytes": 100, "free_inodes": 10}, 0),
    ([10, None], [1, 1], {"status": "available", "free_bytes": 100, "free_inodes": 10}, 0),
    ([-10], [1], {"status": "available", "free_bytes": 100, "free_inodes": 10}, 0),
    ([10], [1], {"status": "available", "free_bytes": float("nan"), "free_inodes": 10}, 0),
    ([10], [1], {"status": "available", "free_bytes": 100, "free_inodes": 10}, None),
    ([True], [1], {"status": "available", "free_bytes": 100, "free_inodes": 10}, 0),
    ([10], [1, None], {"status": "available", "free_bytes": 100, "free_inodes": 10}, 0),
])
def test_incomplete_pilot_or_missing_headroom_cannot_claim_capacity(growth, inodes, capacity, reserve):
    result = forecast_storage(growth, inodes, capacity, reserve_bytes=reserve)
    assert result["status"] == "unavailable"
    assert result["conditional_attempt_capacity"] is None


@pytest.mark.parametrize("count,reserve", [(True, 0), (-1, 0), (1, -1), (1, 2.5)])
def test_invalid_operator_forecast_arguments_are_rejected(count, reserve):
    with pytest.raises(ValueError):
        forecast_storage([], [], {}, planned_attempts=count, reserve_bytes=reserve)


def test_large_integer_growth_does_not_overflow_a_float_conversion():
    result = forecast_storage([10 ** 1000], [1], {"status": "available", "free_bytes": 100, "free_inodes": 10}, reserve_bytes=0)
    assert result["conditional_attempt_capacity"] == 0


def test_report_keeps_failed_and_unknown_costs_and_does_not_use_pc_capacity(tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    root = tmp_path / "original"
    root.mkdir()
    capacities = {"status": "available", "free_bytes": 1000, "free_inodes": 100,
                  "captured_utc": "2026-09-15T00:00:00+00:00", "source": "saved target statvfs"}
    attempts = [{"experiment_id": "original", "run_id": str(index), "device_label": "pi5",
                 "cohort_id": "same", "pair": "astropy-apexpy", "kind": "measured", "status": status,
                 "storage": storage} for index, (status, storage) in enumerate([
                     ("complete", {"capacity_after_retention": capacities, "observed_filesystem_growth_bytes": 100,
                                   "observed_filesystem_growth_inodes": 1, "compression_wall_seconds": 0.01}),
                     ("failed", None)])]
    result = report_storage([{"root": root, "identity": "original"}], attempts, output, planned_attempts=2, reserve_bytes=100)
    group = result["groups"][0]
    assert group["all_started_attempts"] == 2 and group["noncomplete_attempts"] == 1
    assert group["retention_metrics"]["compression_wall_seconds"]["unavailable_attempts"] == 1
    assert group["forecast"]["status"] == "unavailable"
    assert group["forecast"]["capacity_observation"] == capacities
    with gzip.open(output / "storage-costs.jsonl.gz", "rt") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 2 and rows[1]["saved_storage_record"] is None
    assert result["raw_attempts_pruned"] is False
