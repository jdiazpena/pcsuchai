import json
from copy import deepcopy
from pathlib import Path

from pcsuchai.comparison import compare_sessions


def _session(label: str) -> dict:
    stats = {"mean": 1.0, "median": 1.0, "standard_deviation": 0.0, "minimum": 1.0, "maximum": 1.0, "p95": 1.0}
    return {
        "status": "complete", "official": True, "scientific_outputs_consistent": True,
        "device_label": label, "source": {"sha256": "source"},
        "runtime": {"python_version": "3.13.5", "machine": "aarch64", "board_model": label, "packages": {"numpy": "2.5.2"}},
        "settings": {"repeats": 2},
        "inputs": {"data": {"sha256": "input", "size_bytes": 4, "path": "/different/is/okay"}},
        "scenarios": {"astropy-aacgmv2": {"summary": {"external_wall_seconds": stats, "stages": {"orbit": {"wall_seconds": stats}}}}},
    }


def test_comparable_sessions_write_csv(tmp_path: Path) -> None:
    paths = []
    for label in ("pi4", "pi5"):
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(_session(label)))
        paths.append(path)
    result = compare_sessions(paths, tmp_path / "combined")
    assert result["status"] == "comparable"
    assert Path(result["comparison_csv"]).is_file()


def test_package_drift_is_rejected(tmp_path: Path) -> None:
    first, second = _session("pi4"), deepcopy(_session("pi5"))
    second["runtime"]["packages"]["numpy"] = "different"
    paths = []
    for name, data in (("one", first), ("two", second)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(data))
        paths.append(path)
    result = compare_sessions(paths, tmp_path / "rejected")
    assert result["status"] == "not_comparable"
    assert any(item["field"] == "packages" for item in result["mismatches"])
