"""End-to-end orchestration for the first validated processing slice."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .analysis import calculate_particle_weighted_centroid
from .benchmark import BenchmarkRecorder, runtime_metadata
from .data import load_measurements
from .magnetic import convert_magnetic
from .orbit import propagate
from .plot_config import load_plot_specs, select_plot_data
from .plotting import (
    plot_configured_map,
    plot_footpoint_particle_map,
    plot_magnetic_particle_map,
    plot_particle_map,
    plot_time_availability,
)
from .tle import load_tle_history, select_nearest_tles


@dataclass(frozen=True)
class AnalysisOutputs:
    """Paths and counts produced by one complete analysis run."""

    observations: int
    valid_positions: int
    positions_csv: str
    particle_map_png: str
    manifest_json: str
    benchmark_json: str | None
    magnetic_positions_csv: str | None
    magnetic_particle_map_png: str | None
    footpoint_particle_map_png: str | None
    configured_plot_files: tuple[str, ...]


def _write_positions(path, measurements, records, selection, orbit) -> None:
    """Write auditable derived positions and their selected TLE provenance."""

    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["source_row", "time_utc", "particle_count", "latitude_deg", "longitude_deg",
             "altitude_km", "tle_epoch_utc", "tle_offset_seconds", "orbit_backend", "error_code"]
        )
        for index, timestamp in enumerate(measurements.times):
            tle = records[int(selection.indices[index])]
            writer.writerow(
                [int(measurements.source_rows[index]), timestamp.isoformat(), measurements.particle_counts[index],
                 orbit.latitude_deg[index], orbit.longitude_deg[index], orbit.altitude_km[index],
                 tle.epoch.isoformat(), selection.offset_seconds[index], orbit.backend,
                 int(orbit.error_codes[index])]
            )


def _write_magnetic_positions(path, measurements, magnetic) -> None:
    """Write native magnetic products without implying cross-model identity."""

    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "source_row", "time_utc", "particle_count", "magnetic_latitude_deg",
            "magnetic_longitude_deg", "magnetic_local_time_hours",
            "surface_geographic_latitude_deg", "surface_geographic_longitude_deg",
            "mapping_error_deg", "magnetic_backend", "coordinate_system", "error_code",
        ])
        for index, timestamp in enumerate(measurements.times):
            writer.writerow([
                int(measurements.source_rows[index]), timestamp.isoformat(),
                measurements.particle_counts[index], magnetic.latitude_deg[index],
                magnetic.longitude_deg[index], magnetic.local_time_hours[index],
                magnetic.surface_latitude_deg[index], magnetic.surface_longitude_deg[index],
                magnetic.mapping_error_deg[index], magnetic.backend,
                magnetic.coordinate_system, int(magnetic.error_codes[index]),
            ])


def run_analysis(
    measurement_path: str | Path,
    tle_path: str | Path,
    output_dir: str | Path,
    orbit_backend: str = "astropy",
    magnetic_backend: str = "none",
    eop_path: str | Path | None = None,
    limit: int | None = None,
    particle_threshold: float = 0.0,
    plot_config_path: str | Path | None = None,
    benchmark: bool = False,
) -> AnalysisOutputs:
    """Run the first complete local pipeline and write reproducible artifacts."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    recorder = BenchmarkRecorder(benchmark)

    with recorder.measure("load_measurements"):
        measurements = load_measurements(measurement_path).first(limit)
        plot_specs = load_plot_specs(plot_config_path) if plot_config_path is not None else ()
    with recorder.measure("load_and_select_tles"):
        records = load_tle_history(tle_path)
        selection = select_nearest_tles(measurements.times, records)
    with recorder.measure("propagate_orbit"):
        orbit = propagate(orbit_backend, measurements.times, records, selection, eop_path)
    magnetic = None
    if magnetic_backend != "none":
        with recorder.measure("convert_magnetic_coordinates"):
            magnetic = convert_magnetic(magnetic_backend, measurements.times, orbit)
    run_label = (
        f"{orbit_backend}-{magnetic_backend}" if magnetic_backend != "none" else orbit_backend
    )
    positions_path = destination / f"positions-{run_label}.csv"
    with recorder.measure("write_positions"):
        _write_positions(positions_path, measurements, records, selection, orbit)
    map_path = destination / f"particle-map-{run_label}.png"
    with recorder.measure("render_and_write_plot"):
        plot_metadata = plot_particle_map(
            orbit, measurements.particle_counts, map_path, threshold=particle_threshold
        )

    magnetic_positions_path = None
    magnetic_map_path = None
    magnetic_plot_metadata = None
    footpoint_map_path = None
    footpoint_plot_metadata = None
    if magnetic is not None:
        magnetic_positions_path = destination / f"magnetic-positions-{magnetic_backend}.csv"
        with recorder.measure("write_magnetic_positions"):
            _write_magnetic_positions(magnetic_positions_path, measurements, magnetic)
        magnetic_map_path = destination / f"particle-map-magnetic-{magnetic_backend}.png"
        with recorder.measure("render_and_write_magnetic_plot"):
            magnetic_plot_metadata = plot_magnetic_particle_map(
                magnetic, measurements.particle_counts, magnetic_map_path,
                threshold=particle_threshold,
            )
        footpoint_map_path = destination / f"particle-map-footpoint-{magnetic_backend}.png"
        with recorder.measure("render_and_write_footpoint_plot"):
            footpoint_plot_metadata = plot_footpoint_particle_map(
                magnetic, measurements.particle_counts, footpoint_map_path,
                threshold=particle_threshold,
            )

    configured_plot_metadata = []
    configured_plot_files = []
    for spec in plot_specs:
        configured_path = destination / f"{spec.name}.png"
        with recorder.measure(f"render_configured_plot:{spec.name}"):
            selected = select_plot_data(spec, measurements, orbit, magnetic)
            if spec.plot_type == "time_availability":
                metadata = plot_time_availability(
                    spec, selected, measurements.times, configured_path
                )
            else:
                metadata = plot_configured_map(spec, selected, configured_path)
            if spec.calculate_centroid:
                metadata["particle_weighted_centroid"] = calculate_particle_weighted_centroid(
                    spec, measurements, orbit, magnetic
                )
        configured_plot_metadata.append(metadata)
        configured_plot_files.append(str(configured_path))

    valid_positions = int(np.count_nonzero(orbit.error_codes == 0))
    manifest_path = destination / f"manifest-{run_label}.json"
    benchmark_path = destination / f"benchmark-{run_label}.json" if benchmark else None
    manifest = {
        "orbit_backend": orbit_backend,
        "magnetic_backend": magnetic_backend,
        "observations": len(measurements),
        "valid_positions": valid_positions,
        "invalid_positions": len(measurements) - valid_positions,
        "later_tle_assignments": int(np.count_nonzero(selection.offset_seconds < 0)),
        "earlier_tle_assignments": int(np.count_nonzero(selection.offset_seconds >= 0)),
        "maximum_absolute_tle_offset_seconds": float(np.max(np.abs(selection.offset_seconds))),
        "plot": plot_metadata,
        "magnetic_plot": magnetic_plot_metadata,
        "footpoint_plot": footpoint_plot_metadata,
        "configured_plots": configured_plot_metadata,
        "valid_magnetic_positions": (
            int(np.count_nonzero(magnetic.error_codes == 0)) if magnetic is not None else None
        ),
        "inputs": {
            "measurements": str(measurement_path), "tle": str(tle_path),
            "eop": str(eop_path), "plot_config": str(plot_config_path),
        },
        "runtime": runtime_metadata(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if benchmark_path is not None:
        recorder.write_json(benchmark_path)
    return AnalysisOutputs(
        len(measurements), valid_positions, str(positions_path), str(map_path), str(manifest_path),
        str(benchmark_path) if benchmark_path else None,
        str(magnetic_positions_path) if magnetic_positions_path else None,
        str(magnetic_map_path) if magnetic_map_path else None,
        str(footpoint_map_path) if footpoint_map_path else None,
        tuple(configured_plot_files),
    )
