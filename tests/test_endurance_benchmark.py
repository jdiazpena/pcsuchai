import json
import time
import numpy as np
from PIL import Image
import pytest
from pathlib import Path

import pcsuchai.benchmark_suite as suite


@pytest.fixture(autouse=True)
def isolated_mock_campaign_lock(tmp_path, monkeypatch):
    """Isolate mocked orchestration tests; production campaigns share one lock."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "mock-device.lock"))


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
            def image_metadata(name, geographic=False):
                return {"path": str(output / name), "points_rendered": 3,
                        "width_px": 4, "height_px": 2,
                        "rendering": {"filled_markers": True},
                        "geographic_context": ({"source": "bundled Natural Earth 110m", "land_parts": 1, "border_segments": 1} if geographic else None)}
            path.write_text(json.dumps({
                "observations": 3, "valid_positions": 3,
                "valid_magnetic_positions": 3,
                "plot": image_metadata("geographic.png", True),
                "magnetic_plot": image_metadata("magnetic.png"),
                "footpoint_plot": image_metadata("footpoint.png", True),
            }), encoding="utf-8")
        elif role == "benchmark_json":
            path.write_text(json.dumps([_stage()]), encoding="utf-8")
        elif role == "raw_products_npz":
            np.savez_compressed(path, **{name: np.ones(3, dtype=bool) for name in (
                "geographic_particle_map_mask", "magnetic_particle_map_mask", "footpoint_particle_map_mask",
            )})
        elif name.endswith(".png"):
            Image.new("RGB", (4, 2)).save(path)
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


def test_required_temperature_outage_stops_before_an_attempt(tmp_path, monkeypatch):
    original = suite._telemetry_snapshot
    def missing(path):
        value = original(path)
        value["temperature_c"] = None
        return value
    monkeypatch.setattr(suite, "_telemetry_snapshot", missing)
    result = _run(tmp_path, monkeypatch, repeats=2, require_temperature_sensor=True)
    assert result["status"] == "stopped"
    assert result["attempt_counts"]["started"] == 0
    assert result["attempt_counts"]["skipped"] == 2
    assert "SoC temperature" in result["stop_reason"]


def test_required_temperature_outage_also_prevents_warmup(tmp_path, monkeypatch):
    original = suite._telemetry_snapshot
    def missing(path):
        value = original(path)
        value["temperature_c"] = None
        return value
    monkeypatch.setattr(suite, "_telemetry_snapshot", missing)
    monkeypatch.setattr(suite, "_run_child", _fake_child)
    inputs = _inputs(tmp_path)
    result = suite.run_benchmark_suite(tmp_path / "benchmark", *inputs, repeats=1, warmups=1,
                                      scenario_pairs=("astropy-aacgmv2",), minimum_free_bytes=0,
                                      require_temperature_sensor=True, project_root=Path.cwd())
    assert list((tmp_path / "benchmark/warmups").glob("*/*")) == []
    assert result["attempt_counts"]["started"] == 0


def test_sampled_peak_latches_until_active_job_saved_then_stops(tmp_path, monkeypatch):
    original_snapshot = suite._telemetry_snapshot
    readings = iter([40., 40., 40., 81., 40.])
    def sensor(path):
        value = original_snapshot(path)
        value["temperature_c"] = next(readings, 40.)
        return value
    monkeypatch.setattr(suite, "_telemetry_snapshot", sensor)
    # Explicit synchronous sample makes the replay deterministic, not dependent
    # on wall scheduling or a real Pi sensor.
    monkeypatch.setattr(suite._TelemetryJournal, "start", lambda self: self.sample())
    result = _run(tmp_path, monkeypatch, repeats=2, maximum_temperature_c=80.)
    assert result["status"] == "stopped"
    assert result["attempt_counts"]["started"] == 1
    assert result["attempt_counts"]["scientifically_valid"] == 1
    assert result["attempt_counts"]["skipped"] == 1
    saved = json.loads(Path(result["report_path"]).read_text())
    assert saved["thermal_policy_stop"]["temperature_c"] == 81.
    run = next((tmp_path / "benchmark/runs").glob("*/*"))
    assert (run / "cycle-timing.json").is_file()
    assert (run / "products/raw-products.npz").is_file()


def test_duration_finishes_active_job_without_forcing_extra_rounds(tmp_path: Path, monkeypatch) -> None:
    def slow_child(command, *args, **kwargs):
        time.sleep(0.05)
        return _fake_child(command, *args, **kwargs)

    measurements, tle, eop = _inputs(tmp_path)
    monkeypatch.setattr(suite, "_run_child", slow_child)
    result = suite.run_benchmark_suite(
        tmp_path / "benchmark", measurements, tle, eop,
        orbit_backends=("astropy",), magnetic_backends=("aacgmv2",),
        warmups=0, repeats=None, duration_seconds=0.03,
        telemetry_interval_seconds=0.01, minimum_free_bytes=0,
        project_root=Path.cwd(),
    )
    assert result["status"] == "complete"
    assert len(result["scenarios"]["astropy-aacgmv2"]["runs"]) == 1
    assert result["attempt_counts"]["started"] == 1
    assert result["active_elapsed_seconds"] >= 0.05


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
    # The second immutable success was committed before its checkpoint entry.
    # Recover it, do not silently retry that already-consumed scheduled slot.
    assert len(list((destination / "runs").glob("*/*"))) == 2
    assert len(resumed["scenarios"]["astropy-aacgmv2"]["runs"]) == 2
    assert resumed["attempt_counts"]["started"] == 2
    assert len(list(destination.glob("runs/*/*/reconciliation-record.json"))) == 1


def test_resume_partial_and_damaged_records_consume_slots_without_retry(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, repeats=3)
    destination = tmp_path / "benchmark"
    checkpoint_path = destination / "benchmark-session.checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["status"] = "stopped"
    checkpoint["execution_order"] = checkpoint["execution_order"][:1]
    checkpoint["scenarios"]["astropy-aacgmv2"]["runs"] = checkpoint["scenarios"]["astropy-aacgmv2"]["runs"][:1]
    checkpoint_path.write_text(json.dumps(checkpoint))
    directories = sorted(destination.glob("runs/*/*"))
    # Simulate power loss before terminal commit, and a torn terminal record.
    (directories[1] / "run-record.json").unlink()
    (directories[2] / "run-record.json").write_bytes(b'{"torn":')
    original = (directories[2] / "run-record.json").read_bytes()
    monkeypatch.setattr(suite, "_run_child", lambda *_args, **_kwargs: pytest.fail("consumed slot retried"))
    measurements, tle, eop = (tmp_path / name for name in ("measurements.csv", "history.tle", "eop.dat"))
    result = suite.run_benchmark_suite(destination, measurements, tle, eop,
                                     orbit_backends=("astropy",), magnetic_backends=("aacgmv2",),
                                     repeats=3, warmups=0, telemetry_interval_seconds=0.01,
                                     minimum_free_bytes=0, project_root=Path.cwd(), resume=True)
    assert result["attempt_counts"] == {"scheduled": 3, "started": 3, "scientifically_valid": 1,
                                        "failed": 1, "interrupted": 1, "skipped": 0, "automatic_retries": 0}
    assert (directories[2] / "run-record.json").read_bytes() == original
    assert len(list(destination.glob("runs/*/*"))) == 3


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
    assert result["attempt_counts"] == {
        "scheduled": 3, "started": 3, "scientifically_valid": 2,
        "failed": 1, "interrupted": 0, "skipped": 0, "automatic_retries": 0,
    }


def test_timed_resume_after_abrupt_exit_does_not_invent_remaining_budget(tmp_path, monkeypatch):
    original = _run(tmp_path, monkeypatch, repeats=None, duration_seconds=0.001)
    destination = tmp_path / "benchmark"
    checkpoint_path = destination / "benchmark-session.checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["status"] = "running"
    checkpoint["execution_order"] = []
    checkpoint["scenarios"]["astropy-aacgmv2"]["runs"] = []
    checkpoint["active_elapsed_seconds"] = 0
    checkpoint_path.write_text(json.dumps(checkpoint))
    monkeypatch.setattr(suite, "_run_child", lambda *_args, **_kwargs: pytest.fail("unknown remaining duration used to launch work"))
    measurements, tle, eop = (tmp_path / name for name in ("measurements.csv", "history.tle", "eop.dat"))
    recovered = suite.run_benchmark_suite(destination, measurements, tle, eop,
                                         orbit_backends=("astropy",), magnetic_backends=("aacgmv2",),
                                         repeats=None, duration_seconds=0.001, warmups=0,
                                         telemetry_interval_seconds=0.01, minimum_free_bytes=0,
                                         project_root=Path.cwd(), resume=True)
    assert recovered["status"] == "stopped"
    assert "cannot recover exact measured duration" in recovered["stop_reason"]
    assert recovered["attempt_counts"]["started"] == original["attempt_counts"]["started"]
    assert recovered["attempt_counts"]["scientifically_valid"] == 1


def test_requested_thermal_condition_cannot_pass_without_sensor(tmp_path, monkeypatch):
    monkeypatch.setattr(suite, "_temperature_c", lambda: None)
    result = _run(tmp_path, monkeypatch, repeats=2, cooldown_until_c=45)
    assert result["status"] == "stopped"
    assert "thermal condition" in result["stop_reason"]
    assert result["attempt_counts"]["started"] == 0
    assert result["attempt_counts"]["skipped"] == 2
    assert not (tmp_path / "benchmark" / "runs").exists()


def test_warmups_do_not_consume_measured_deadline(tmp_path, monkeypatch):
    calls = []

    def slow_child(command, *args, **kwargs):
        calls.append(command)
        time.sleep(0.05)
        return _fake_child(command, *args, **kwargs)

    measurements, tle, eop = _inputs(tmp_path)
    monkeypatch.setattr(suite, "_run_child", slow_child)
    result = suite.run_benchmark_suite(
        tmp_path / "benchmark", measurements, tle, eop,
        orbit_backends=("astropy",), magnetic_backends=("aacgmv2",),
        warmups=1, repeats=None, duration_seconds=0.03,
        minimum_free_bytes=0, telemetry_interval_seconds=0.01,
        project_root=Path.cwd(),
    )
    assert len(calls) == 2
    assert result["attempt_counts"]["started"] == 1
    assert result["execution_order"][0]["kind"] == "warmup"
