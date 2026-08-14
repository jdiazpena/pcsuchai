import json
from pathlib import Path

from pcsuchai.pipeline import run_analysis


ROOT = Path(__file__).parents[1]


def test_first_slice_writes_outputs_and_optional_benchmark(tmp_path) -> None:
    outputs = run_analysis(
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        tmp_path,
        orbit_backend="astropy",
        eop_path=ROOT / "data/eop/finals2000A.all",
        limit=40,
        particle_threshold=0,
        benchmark=True,
    )

    assert outputs.observations == 40
    assert outputs.valid_positions == 40
    assert Path(outputs.positions_csv).stat().st_size > 0
    assert Path(outputs.particle_map_png).stat().st_size > 0
    manifest = json.loads(Path(outputs.manifest_json).read_text())
    metrics = json.loads(Path(outputs.benchmark_json).read_text())
    assert manifest["plot"]["points_rendered"] == 40
    assert {item["stage"] for item in metrics} == {
        "load_measurements", "load_and_select_tles", "propagate_orbit",
        "write_positions", "render_and_write_plot",
    }


def test_pipeline_writes_aacgm_products(tmp_path) -> None:
    outputs = run_analysis(
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        tmp_path,
        orbit_backend="astropy",
        magnetic_backend="aacgmv2",
        eop_path=ROOT / "data/eop/finals2000A.all",
        limit=8,
        benchmark=True,
    )

    assert Path(outputs.magnetic_positions_csv).stat().st_size > 0
    assert Path(outputs.magnetic_particle_map_png).stat().st_size > 0
    assert Path(outputs.footpoint_particle_map_png).stat().st_size > 0
    manifest = json.loads(Path(outputs.manifest_json).read_text())
    assert manifest["magnetic_backend"] == "aacgmv2"
    assert manifest["valid_magnetic_positions"] == 8
    stages = [item["stage"] for item in json.loads(Path(outputs.benchmark_json).read_text())]
    assert stages.index("propagate_orbit") < stages.index("convert_magnetic_coordinates")
    assert "render_and_write_footpoint_plot" in stages


def test_pipeline_applies_configured_plot_profile(tmp_path) -> None:
    config = tmp_path / "plots.json"
    config.write_text(json.dumps({"plots": [
        {"name": "filled_footpoints", "coordinate_view": "footpoint", "marker_size": 25},
        {"name": "availability", "plot_type": "time_availability", "height_px": 300},
    ]}))
    outputs = run_analysis(
        ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle", tmp_path,
        orbit_backend="astropy", magnetic_backend="aacgmv2",
        eop_path=ROOT / "data/eop/finals2000A.all", limit=12,
        plot_config_path=config,
    )
    assert len(outputs.configured_plot_files) == 2
    assert all(Path(item).stat().st_size > 0 for item in outputs.configured_plot_files)
