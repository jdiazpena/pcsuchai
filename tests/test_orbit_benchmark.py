from pathlib import Path

from pcsuchai.orbit_benchmark import run_orbit_benchmark


ROOT = Path(__file__).parents[1]


def test_repeated_orbit_benchmark_uses_clean_processes_and_hashes(tmp_path: Path) -> None:
    result = run_orbit_benchmark(
        tmp_path / "orbit-benchmark", ROOT,
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        ROOT / "data/eop/finals2000A.all",
        repeats=2, warmups=0, limit=3,
    )
    assert result["status"] == "complete"
    assert result["official"] is False
    assert result["scientific_outputs_consistent"]
    assert len(result["execution_order"]) == 4
    for backend in ("astropy", "skyfield"):
        assert len(result["backends"][backend]["runs"]) == 2
        assert "wall_seconds" in result["backends"][backend]["summary"]["propagation_stage"]
