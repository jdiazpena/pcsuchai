from pathlib import Path

import pytest

from pcsuchai.benchmark_suite import _statistics, parse_perf_stat, run_benchmark_suite


def test_repeat_statistics_are_complete() -> None:
    result = _statistics([1.0, 2.0, 3.0])
    assert result["mean"] == 2.0
    assert result["median"] == 2.0
    assert result["minimum"] == 1.0
    assert result["maximum"] == 3.0
    assert result["p95"] == 2.9


def test_perf_parser_records_values_and_unsupported_counters(tmp_path: Path) -> None:
    path = tmp_path / "perf.csv"
    path.write_text("12345;;cycles;1;100.00\n<not supported>;;instructions;0;0\n")
    result = parse_perf_stat(path)
    assert result["cycles"] == 12345.0
    assert result["instructions"] is None


def test_official_benchmark_refuses_to_run_without_certificate(tmp_path: Path) -> None:
    for name in ("measurements", "tle", "eop", "plots"):
        (tmp_path / name).write_text("placeholder")
    with pytest.raises(ValueError, match="complete Astropy/Skyfield"):
        run_benchmark_suite(
            tmp_path / "out", tmp_path / "measurements", tmp_path / "tle",
            tmp_path / "eop", plot_config=tmp_path / "plots",
            orbit_backends=("astropy",), magnetic_backends=("aacgmv2",),
            repeats=2, official=True,
        )


def test_official_full_matrix_still_requires_certificate(tmp_path: Path) -> None:
    for name in ("measurements", "tle", "eop", "plots"):
        (tmp_path / name).write_text("placeholder")
    with pytest.raises(ValueError, match="validation certificate"):
        run_benchmark_suite(
            tmp_path / "out", tmp_path / "measurements", tmp_path / "tle",
            tmp_path / "eop", plot_config=tmp_path / "plots",
            repeats=2, official=True,
        )
