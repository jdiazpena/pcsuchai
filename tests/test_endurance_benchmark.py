import json
from pathlib import Path

import pcsuchai.benchmark_suite as suite


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = tuple(tmp_path / name for name in ("measurements.csv", "history.tle", "eop.dat"))
    for index, path in enumerate(paths):
        path.write_text(f"input-{index}\n", encoding="utf-8")
    return paths


def _stage() -> dict:
    numeric = {
        "wall_seconds", "process_cpu_seconds", "process_user_seconds",
        "process_system_seconds", "peak_rss_bytes", "read_bytes", "write_bytes",
        "read_chars", "write_chars", "rss_change_bytes", "cpu_equivalent_percent",
        "voluntary_context_switches", "involuntary_context_switches",
        "minor_page_faults", "major_page_faults", "peak_threads",
        "available_memory_start_bytes", "available_memory_min_bytes",
        "available_memory_end_bytes", "temperature_start_c", "temperature_max_c",
        "temperature_end_c", "cpu_frequency_min_mhz", "cpu_frequency_max_mhz",
    }
    return {
        "stage": "complete_pipeline",
        "started_utc": "2026-01-01T00:00:00+00:00",
        "finished_utc": "2026-01-01T00:00:01+00:00",
        **{name: 1 for name in numeric},
        "throttled_start": "0x0", "throttled_end": "0x0",
    }


def _fake_child(command: list[str], *_args, **_kwargs) -> tuple[dict, float, str]:
    output = Path(command[command.index("--output-dir") + 1])
    output.mkdir(parents=True, exist_ok=False)
    names = {
        "positions_csv": "positions.csv",
        "particle_map_png": "geographic.png",
        "manifest_json": "manifest.json",
        "benchmark_json": "benchmark.json",
        "magnetic_positions_csv": "magnetic.csv",
        "magnetic_particle_map_png": "magnetic.png",
        "footpoint_particle_map_png": "footpoint.png",
        "raw_products_npz": "raw-products.npz",
        "raw_benchmark_samples": "benchmark.samples.csv.gz",
    }
    result = {}
    for role, name in names.items():
        path = output / name
        if role == "manifest_json":
            path.write_text(json.dumps({
                "observations": 3, "valid_positions": 3,
                "valid_magnetic_positions": 3,
            }), encoding="utf-8")
        elif role == "benchmark_json":
            path.write_text(json.dumps([_stage()]), encoding="utf-8")
        else:
            path.write_bytes(b"stable scientific product\n")
        result[role] = str(path)
    result["configured_plot_files"] = []
    result["plot_selection_files"] = []
    return result, 0.01, ""


def _run(tmp_path: Path, monkeypatch, **options) -> dict:
    monkeypatch.setattr(suite, "_run_child", _fake_child)
    measurements, tle, eop = _inputs(tmp_path)
    return suite.run_benchmark_suite(
        tmp_path / "benchmark", measurements, tle, eop,
        orbit_backends=("astropy",), magnetic_backends=("aacgmv2",),
        warmups=0, telemetry_interval_seconds=0.01, minimum_free_bytes=0,
        project_root=Path.cwd(), **options,
    )


def test_every_run_has_timestamped_durable_directory_and_telemetry(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, repeats=2)

    run_directories = sorted((tmp_path / "benchmark" / "runs").glob("*/*"))
    assert result["status"] == "complete"
    assert len(run_directories) == 2
    assert all(directory.name.endswith("-astropy-aacgmv2") for directory in run_directories)
    assert all((directory / "run-record.json").is_file() for directory in run_directories)
    assert all((directory / "system-telemetry.csv.gz").is_file() for directory in run_directories)
    assert all((directory / "products").is_dir() for directory in run_directories)
    assert (tmp_path / "benchmark" / "campaign-events.jsonl").is_file()
    assert list((tmp_path / "benchmark").glob("system-telemetry.*.csv.gz"))
    assert (tmp_path / "benchmark" / "heartbeat.json").is_file()
    assert result["settings"]["artifact_retention"] == "all"
    assert result["input_snapshots"]["measurements"]["path"].endswith(".gz")
    assert (tmp_path / "benchmark" / "source-snapshot.tar.gz").is_file()
    assert all("record_path" in ref for ref in result["scenarios"]["astropy-aacgmv2"]["runs"])
    first, second = [directory / "products/positions.csv" for directory in run_directories]
    assert first.stat().st_ino == second.stat().st_ino
    assert suite._load_run(result["scenarios"]["astropy-aacgmv2"]["runs"][1])["storage"]["shared_files"] > 0


def test_duration_mode_finishes_complete_rounds_and_minimum_two(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, repeats=None, duration_seconds=0.001)

    assert result["status"] == "complete"
    assert len(result["scenarios"]["astropy-aacgmv2"]["runs"]) == 2


def test_resume_keeps_abandoned_folder_and_completes_checkpoint(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, repeats=2)
    destination = tmp_path / "benchmark"
    checkpoint_path = destination / "benchmark-session.checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["status"] = "stopped"
    checkpoint["execution_order"] = checkpoint["execution_order"][:1]
    checkpoint["scenarios"]["astropy-aacgmv2"]["runs"] = [
        checkpoint["scenarios"]["astropy-aacgmv2"]["runs"][0]
    ]
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    measurements, tle, eop = (tmp_path / name for name in ("measurements.csv", "history.tle", "eop.dat"))
    resumed = suite.run_benchmark_suite(
        destination, measurements, tle, eop,
        orbit_backends=("astropy",), magnetic_backends=("aacgmv2",), repeats=2,
        warmups=0, telemetry_interval_seconds=0.01, minimum_free_bytes=0,
        project_root=Path.cwd(), resume=True,
    )

    assert result["status"] == resumed["status"] == "complete"
    assert len(resumed["resume_events"]) == 1
    assert len(list((destination / "runs").glob("*/*"))) == 3
    assert len(resumed["scenarios"]["astropy-aacgmv2"]["runs"]) == 2


def test_failed_attempt_is_preserved_and_campaign_can_continue(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def fail_once(command, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("deliberate child failure")
        return _fake_child(command, *args, **kwargs)

    monkeypatch.setattr(suite, "_run_child", fail_once)
    measurements, tle, eop = _inputs(tmp_path)
    result = suite.run_benchmark_suite(
        tmp_path / "benchmark", measurements, tle, eop,
        orbit_backends=("astropy",), magnetic_backends=("aacgmv2",), repeats=3,
        warmups=0, telemetry_interval_seconds=0.01, minimum_free_bytes=0,
        project_root=Path.cwd(), continue_on_error=True,
    )

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "benchmark" / "runs").glob("*/*/run-record.json")
    ]
    assert result["status"] == "complete"
    assert sorted(record["status"] for record in records) == ["complete", "complete", "failed"]
    assert result["failures"][0]["error"] == "deliberate child failure"
