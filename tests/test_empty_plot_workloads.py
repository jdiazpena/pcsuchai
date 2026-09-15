import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from pcsuchai.benchmark_suite import _validate_run
from pcsuchai.pipeline import run_analysis
from pcsuchai.product_validation import validate_pipeline_images
from pcsuchai.models import MagneticResult, OrbitResult
from pcsuchai.plotting import plot_particle_map, plot_magnetic_particle_map, plot_footpoint_particle_map


ROOT = Path(__file__).resolve().parents[1]


def test_small_full_profile_keeps_every_filter_image_and_raw_mask(tmp_path):
    outputs = run_analysis(ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle",
                           tmp_path / "products", orbit_backend="skyfield", magnetic_backend="apexpy",
                           eop_path=ROOT / "data/eop/finals2000A.all", limit=100,
                           plot_config_path=ROOT / "configs/plots/archive-full.json", benchmark=True)
    manifest = json.loads(Path(outputs.manifest_json).read_text())
    assert len(outputs.configured_plot_files) == len(outputs.plot_selection_files) == 32
    assert len(manifest["configured_plots"]) == 32
    empty = [row for row in manifest["configured_plots"] if row["data_status"] == "empty_selection"]
    assert empty, "a tiny prefix must not be treated as covering all science filters"
    for metadata, path in zip(manifest["configured_plots"], outputs.plot_selection_files):
        with np.load(path, allow_pickle=False) as arrays:
            assert np.count_nonzero(arrays["mask"]) == metadata["points_rendered"]
        if metadata["data_status"] == "empty_selection":
            assert metadata["points_rendered"] == 0
            if metadata.get("plot_type") != "time_availability":
                assert metadata["value_min"] is metadata["value_max"] is None
            centroid = metadata.get("particle_weighted_centroid")
            if centroid:
                assert centroid["status"] == "unavailable"
                assert centroid["latitude_deg"] is centroid["longitude_deg"] is None
    verified = _validate_run(asdict(outputs), 1.0)
    assert verified["image_validation"]["passed"]
    assert len(verified["image_validation"]["images"]) == 35
    assert validate_pipeline_images(manifest, outputs.raw_products_npz, outputs.plot_selection_files)["passed"]


def test_empty_default_maps_preserve_context_without_fabricated_observations(tmp_path):
    orbit = OrbitResult(latitude_deg=np.array([0.0]), longitude_deg=np.array([0.0]),
                        altitude_km=np.array([500.0]), error_codes=np.array([0]), backend="test")
    magnetic = MagneticResult(latitude_deg=np.array([0.0]), longitude_deg=np.array([0.0]),
                              local_time_hours=np.array([12.0]), surface_latitude_deg=np.array([0.0]),
                              surface_longitude_deg=np.array([0.0]), mapping_error_deg=np.array([0.0]),
                              error_codes=np.array([0]), backend="test", coordinate_system="test")
    counts = np.array([np.nan])
    manifest = {
        "plot": plot_particle_map(orbit, counts, tmp_path / "geo.png"),
        "magnetic_plot": plot_magnetic_particle_map(magnetic, counts, tmp_path / "mag.png"),
        "footpoint_plot": plot_footpoint_particle_map(magnetic, counts, tmp_path / "foot.png"),
    }
    for row in manifest.values():
        assert row["points_rendered"] == 0 and row["data_status"] == "empty_selection"
    raw = tmp_path / "raw.npz"
    np.savez_compressed(raw, **{name: np.array([False]) for name in (
        "geographic_particle_map_mask", "magnetic_particle_map_mask", "footpoint_particle_map_mask")})
    assert validate_pipeline_images(manifest, raw, ())["passed"]
