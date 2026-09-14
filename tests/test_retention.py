"""Unit checks for lossless storage; no orbit or magnetic analysis is executed."""

import csv
import gzip
import io
import sys
from pathlib import Path

import numpy as np
import pytest

from pcsuchai.retention import (
    RawSampleJournal, compress_retained_file, deduplicate_products, snapshot_inputs,
)
from pcsuchai.benchmark_suite import _run_child
from pcsuchai.benchmark import BenchmarkRecorder
from pcsuchai.pipeline import _write_plot_selection
from pcsuchai.plot_config import PlotSelection


def test_gzip_is_byte_exact_and_deterministic(tmp_path: Path) -> None:
    payload = b"time\tvalue\r\n2018-01-01\tinf\r\n" * 100
    first, second = tmp_path / "one.csv", tmp_path / "two.csv"
    first.write_bytes(payload)
    second.write_bytes(payload)
    left = compress_retained_file(first, remove_original=True)
    right = compress_retained_file(second, remove_original=True)
    assert gzip.decompress(left.read_bytes()) == payload
    assert left.read_bytes() == right.read_bytes()
    assert not first.exists() and not second.exists()


def test_gzip_never_overwrites_an_existing_archive(tmp_path: Path) -> None:
    original = tmp_path / "raw.csv"
    original.write_bytes(b"old")
    saved = compress_retained_file(original)
    original.write_bytes(b"new")
    with pytest.raises(FileExistsError):
        compress_retained_file(original, remove_original=True)
    assert original.read_bytes() == b"new"
    assert gzip.decompress(saved.read_bytes()) == b"old"


def test_raw_journal_preserves_every_row(tmp_path: Path) -> None:
    journal = RawSampleJournal(tmp_path / "samples.csv", ("time", "value"))
    values = [float("inf"), float("nan"), -0.0, 1.2345678901234567]
    for index, value in enumerate(values):
        journal.append({"time": index, "value": value})
    saved = journal.finish()
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(saved.read_bytes()).decode())))
    assert len(rows) == len(values)
    assert [row["value"] for row in rows] == [str(value) for value in values]


def test_identical_products_share_storage_but_changed_products_do_not(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        (directory / "plot.png").write_bytes(b"identical")
    (first / "science.csv").write_bytes(b"1")
    (second / "science.csv").write_bytes(b"2")
    deduplicate_products(first, tmp_path / "store")
    result = deduplicate_products(second, tmp_path / "store")
    assert result["shared_files"] == 1
    assert (first / "plot.png").stat().st_ino == (second / "plot.png").stat().st_ino
    assert (first / "science.csv").stat().st_ino != (second / "science.csv").stat().st_ino
    assert (second / "science.csv").read_bytes() == b"2"


def test_input_snapshot_survives_original_input_change(tmp_path: Path) -> None:
    original = tmp_path / "input.csv"
    original.write_bytes(b"original bytes\r\n")
    record = snapshot_inputs({"measurements": original}, tmp_path / "inputs")
    original.write_bytes(b"changed")
    saved = Path(record["measurements"]["path"])
    assert gzip.decompress(saved.read_bytes()) == b"original bytes\r\n"


def test_full_plot_selection_keeps_nonfinite_values_and_exact_mask(tmp_path: Path) -> None:
    selected = PlotSelection(
        np.array([True, False, True]), np.array([1., 2., 3.]), np.array([4., 5., 6.]),
        np.array([0.12345678901234567, np.inf, -0.0]), "x", "y", "value", "linear",
    )
    path = tmp_path / "selection.npz"
    _write_plot_selection(path, selected)
    with np.load(path, allow_pickle=False) as data:
        assert np.array_equal(data["mask"], selected.mask)
        assert data["values"].tobytes() == selected.values.tobytes()


def test_failed_child_retains_complete_logs_not_only_tail(tmp_path: Path) -> None:
    products = tmp_path / "run/products"
    command = [
        sys.executable, "-c",
        "import sys; sys.stdout.write('a'*10000); sys.stderr.write('b'*15000); sys.exit(3)",
        "--output-dir", str(products),
    ]
    with pytest.raises(RuntimeError, match="complete logs"):
        _run_child(command, 10)
    assert (products.parent / "stdout.log").read_bytes() == b"a" * 10000
    assert (products.parent / "stderr.log").read_bytes() == b"b" * 15000


def test_recorder_keeps_stage_boundary_samples_in_addition_to_summaries(tmp_path: Path) -> None:
    recorder = BenchmarkRecorder(True, sample_path=tmp_path / "raw.samples.csv")
    with recorder.measure("unit-no-science"):
        pass
    summary = tmp_path / "benchmark.json"
    recorder.write_json(summary)
    with gzip.open(recorder.raw_sample_path, "rt", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["phase"] for row in rows] == ["start", "end"]
    assert all(row["captured_utc"] and row["rss_bytes"] for row in rows)
    assert summary.is_file()
