"""Quantitative comparisons between interchangeable processing backends."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .models import MagneticResult, OrbitResult


def _statistics(values: np.ndarray) -> dict[str, float]:
    """Return stable summary statistics for a finite numeric vector."""

    return {
        "count": int(len(values)),
        "minimum": float(np.min(values)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "standard_deviation": float(np.std(values)),
        "rmse": float(np.sqrt(np.mean(np.square(values)))),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(np.max(values)),
    }


def _error_histogram(codes: np.ndarray) -> dict[str, int]:
    """Return JSON-safe propagation error counts."""

    values, counts = np.unique(codes, return_counts=True)
    return {str(int(value)): int(count) for value, count in zip(values, counts)}


def _ecef_km(latitude_deg: np.ndarray, longitude_deg: np.ndarray, altitude_km: np.ndarray) -> np.ndarray:
    """Convert WGS84 geodetic positions to Earth-centred Cartesian kilometres."""

    semi_major = 6378.137
    eccentricity_squared = 6.69437999014e-3
    latitude = np.deg2rad(latitude_deg)
    longitude = np.deg2rad(longitude_deg)
    prime_vertical = semi_major / np.sqrt(1.0 - eccentricity_squared * np.sin(latitude) ** 2)
    x = (prime_vertical + altitude_km) * np.cos(latitude) * np.cos(longitude)
    y = (prime_vertical + altitude_km) * np.cos(latitude) * np.sin(longitude)
    z = (prime_vertical * (1.0 - eccentricity_squared) + altitude_km) * np.sin(latitude)
    return np.column_stack((x, y, z))


def _orbit_differences(first: OrbitResult, second: OrbitResult) -> dict[str, np.ndarray]:
    """Calculate signed and physical differences for jointly valid positions."""

    valid = (first.error_codes == 0) & (second.error_codes == 0)
    latitude_signed = first.latitude_deg[valid] - second.latitude_deg[valid]
    longitude_signed = (
        first.longitude_deg[valid] - second.longitude_deg[valid] + 180.0
    ) % 360.0 - 180.0
    altitude_signed = first.altitude_km[valid] - second.altitude_km[valid]
    lat1, lat2 = np.deg2rad(first.latitude_deg[valid]), np.deg2rad(second.latitude_deg[valid])
    dlat, dlon = lat1 - lat2, np.deg2rad(longitude_signed)
    haversine = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    surface_distance = 2.0 * 6371.0088 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
    ecef_first = _ecef_km(
        first.latitude_deg[valid], first.longitude_deg[valid], first.altitude_km[valid]
    )
    ecef_second = _ecef_km(
        second.latitude_deg[valid], second.longitude_deg[valid], second.altitude_km[valid]
    )
    return {
        "valid": valid,
        "latitude_signed_deg": latitude_signed,
        "longitude_signed_deg": longitude_signed,
        "altitude_signed_km": altitude_signed,
        "surface_distance_km": surface_distance,
        "position_3d_distance_km": np.linalg.norm(ecef_first - ecef_second, axis=1),
    }


def compare_raw_sgp4_wrappers(times, records, selection) -> dict:
    """Verify direct SGP4 and Skyfield configure the same raw TEME propagation."""

    from sgp4.api import Satrec, jday
    from skyfield.api import EarthSatellite, load

    year = np.asarray([item.year for item in times])
    month = np.asarray([item.month for item in times])
    day = np.asarray([item.day for item in times])
    hour = np.asarray([item.hour for item in times])
    minute = np.asarray([item.minute for item in times])
    second = np.asarray([
        item.second + item.microsecond / 1_000_000.0 for item in times
    ])
    jd, fraction = jday(year, month, day, hour, minute, second)
    direct_errors = np.full(len(times), -1, dtype=np.int16)
    skyfield_errors = np.full(len(times), -1, dtype=np.int16)
    position_difference = np.full(len(times), np.nan)
    velocity_difference = np.full(len(times), np.nan)
    timescale = load.timescale(builtin=True)
    for tle_index in np.unique(selection.indices):
        positions = np.flatnonzero(selection.indices == tle_index)
        record = records[int(tle_index)]
        direct = Satrec.twoline2rv(record.line1, record.line2)
        skyfield_model = EarthSatellite(
            record.line1, record.line2, f"SUCHAI-1-{tle_index}", timescale
        ).model
        error_a, position_a, velocity_a = direct.sgp4_array(jd[positions], fraction[positions])
        error_b, position_b, velocity_b = skyfield_model.sgp4_array(jd[positions], fraction[positions])
        direct_errors[positions] = error_a
        skyfield_errors[positions] = error_b
        valid = (error_a == 0) & (error_b == 0)
        valid_positions = positions[valid]
        position_difference[valid_positions] = np.linalg.norm(
            position_a[valid] - position_b[valid], axis=1
        )
        velocity_difference[valid_positions] = np.linalg.norm(
            velocity_a[valid] - velocity_b[valid], axis=1
        )
    joint = np.isfinite(position_difference) & np.isfinite(velocity_difference)
    errors_match = bool(np.array_equal(direct_errors, skyfield_errors))
    maximum_position = float(np.max(position_difference[joint])) if np.any(joint) else None
    maximum_velocity = float(np.max(velocity_difference[joint])) if np.any(joint) else None
    passed = (
        errors_match and maximum_position is not None and maximum_position <= 1e-9
        and maximum_velocity is not None and maximum_velocity <= 1e-12
    )
    return {
        "status": "pass" if passed else "fail",
        "interpretation": (
            "This confirms identical TLE/time configuration at the raw SGP4 TEME layer. "
            "It is not an independent physical-model comparison."
        ),
        "positions_compared": int(np.count_nonzero(joint)),
        "error_codes_match": errors_match,
        "direct_error_codes": _error_histogram(direct_errors),
        "skyfield_model_error_codes": _error_histogram(skyfield_errors),
        "maximum_teme_position_difference_km": maximum_position,
        "maximum_teme_velocity_difference_km_s": maximum_velocity,
        "position_limit_km": 1e-9, "velocity_limit_km_s": 1e-12,
    }


def compare_orbits(first: OrbitResult, second: OrbitResult) -> dict:
    """Assess consistency between two implementations of the same SGP4 workload."""

    if len(first.latitude_deg) != len(second.latitude_deg):
        raise ValueError("orbit results have different lengths")
    first_valid = first.error_codes == 0
    second_valid = second.error_codes == 0
    valid = first_valid & second_valid
    if not np.any(valid):
        raise ValueError("orbit results have no jointly valid positions")
    differences = _orbit_differences(first, second)
    lat = np.abs(differences["latitude_signed_deg"])
    lon = np.abs(differences["longitude_signed_deg"])
    alt = np.abs(differences["altitude_signed_km"])
    unmatched_validity = int(np.count_nonzero(first_valid ^ second_valid))
    criteria = {
        "unmatched_validity_count": {"limit": 0, "observed": unmatched_validity, "passed": unmatched_validity == 0},
        "maximum_latitude_difference_deg": {"limit": 0.01, "observed": float(np.max(lat)), "passed": bool(np.max(lat) <= 0.01)},
        "maximum_longitude_difference_deg": {"limit": 0.01, "observed": float(np.max(lon)), "passed": bool(np.max(lon) <= 0.01)},
        "maximum_altitude_difference_km": {"limit": 0.1, "observed": float(np.max(alt)), "passed": bool(np.max(alt) <= 0.1)},
    }

    return {
        "interpretation": (
            "Cross-implementation consistency for two software paths using the same "
            "TLEs and SGP4 model; agreement is required but is not validation against truth."
        ),
        "first_backend": first.backend,
        "second_backend": second.backend,
        "positions_total": len(first.latitude_deg),
        "first_valid_positions": int(first_valid.sum()),
        "second_valid_positions": int(second_valid.sum()),
        "positions_compared": int(valid.sum()),
        "first_only_valid_positions": int(np.count_nonzero(first_valid & ~second_valid)),
        "second_only_valid_positions": int(np.count_nonzero(~first_valid & second_valid)),
        "both_invalid_positions": int(np.count_nonzero(~first_valid & ~second_valid)),
        "first_error_codes": _error_histogram(first.error_codes),
        "second_error_codes": _error_histogram(second.error_codes),
        "latitude_difference_deg": _statistics(lat),
        "longitude_difference_deg": _statistics(lon),
        "altitude_difference_km": _statistics(alt),
        "surface_separation_km": _statistics(differences["surface_distance_km"]),
        "position_3d_separation_km": _statistics(differences["position_3d_distance_km"]),
        "acceptance_criteria": criteria,
        "consistency_status": "pass" if all(item["passed"] for item in criteria.values()) else "fail",
    }


def compare_magnetic(first: MagneticResult, second: MagneticResult) -> dict:
    """Describe two native magnetic outputs without scoring model accuracy.

    Difference statistics are diagnostic only because AACGM and modified-apex
    coordinates have different definitions. Performance is recorded separately
    by ``validate_magnetic_backends`` and is the primary onboard comparison.
    """

    if len(first.latitude_deg) != len(second.latitude_deg):
        raise ValueError("magnetic results have different lengths")
    first_valid = first.error_codes == 0
    second_valid = second.error_codes == 0
    jointly_valid = first_valid & second_valid
    if not np.any(jointly_valid):
        raise ValueError("magnetic results have no jointly valid positions")
    lat = np.abs(first.latitude_deg[jointly_valid] - second.latitude_deg[jointly_valid])
    lon = np.abs(
        (first.longitude_deg[jointly_valid] - second.longitude_deg[jointly_valid] + 180) % 360
        - 180
    )
    mlt = np.abs(
        (first.local_time_hours[jointly_valid] - second.local_time_hours[jointly_valid] + 12)
        % 24 - 12
    )
    return {
        "interpretation": (
            "Diagnostic differences between distinct coordinate systems; these are not "
            "accuracy errors and smaller values do not identify a better backend."
        ),
        "first_backend": first.backend,
        "first_coordinate_system": first.coordinate_system,
        "second_backend": second.backend,
        "second_coordinate_system": second.coordinate_system,
        "positions_total": len(first.latitude_deg),
        "first_valid_positions": int(first_valid.sum()),
        "second_valid_positions": int(second_valid.sum()),
        "positions_compared": int(jointly_valid.sum()),
        "first_only_valid_positions": int(np.count_nonzero(first_valid & ~second_valid)),
        "second_only_valid_positions": int(np.count_nonzero(~first_valid & second_valid)),
        "both_invalid_positions": int(np.count_nonzero(~first_valid & ~second_valid)),
        "first_error_codes": _error_histogram(first.error_codes),
        "second_error_codes": _error_histogram(second.error_codes),
        "native_latitude_difference_deg": _statistics(lat),
        "native_longitude_difference_deg": _statistics(lon),
        "magnetic_local_time_difference_hours": _statistics(mlt),
    }


def _write_magnetic_differences(path, measurements, orbit, first, second) -> None:
    """Write both native magnetic results and diagnostic differences per row."""

    first_valid = first.error_codes == 0
    second_valid = second.error_codes == 0
    joint = first_valid & second_valid
    lat_difference = np.full(len(measurements), np.nan)
    lon_difference = np.full(len(measurements), np.nan)
    mlt_difference = np.full(len(measurements), np.nan)
    lat_difference[joint] = np.abs(first.latitude_deg[joint] - second.latitude_deg[joint])
    lon_difference[joint] = np.abs(
        (first.longitude_deg[joint] - second.longitude_deg[joint] + 180.0) % 360.0 - 180.0
    )
    mlt_difference[joint] = np.abs(
        (first.local_time_hours[joint] - second.local_time_hours[joint] + 12.0) % 24.0 - 12.0
    )
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "source_row", "time_utc", "orbit_latitude_deg", "orbit_longitude_deg", "orbit_altitude_km",
            "aacgm_error_code", "aacgm_latitude_deg", "aacgm_longitude_deg", "aacgm_mlt_hours",
            "aacgm_surface_latitude_deg", "aacgm_surface_longitude_deg",
            "apex_error_code", "apex_latitude_deg", "apex_longitude_deg", "apex_mlt_hours",
            "apex_surface_latitude_deg", "apex_surface_longitude_deg",
            "native_latitude_difference_deg", "native_longitude_difference_deg", "mlt_difference_hours",
        ])
        for index, timestamp in enumerate(measurements.times):
            writer.writerow([
                int(measurements.source_rows[index]), timestamp.isoformat(), orbit.latitude_deg[index],
                orbit.longitude_deg[index], orbit.altitude_km[index], int(first.error_codes[index]),
                first.latitude_deg[index], first.longitude_deg[index], first.local_time_hours[index],
                first.surface_latitude_deg[index], first.surface_longitude_deg[index],
                int(second.error_codes[index]), second.latitude_deg[index], second.longitude_deg[index],
                second.local_time_hours[index], second.surface_latitude_deg[index],
                second.surface_longitude_deg[index], lat_difference[index], lon_difference[index],
                mlt_difference[index],
            ])


def write_comparison(path: str | Path, comparison: dict) -> None:
    """Write a backend comparison as machine-readable JSON."""

    Path(path).write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")


def _write_orbit_differences(path, measurements, records, selection, first, second) -> None:
    """Write row-level orbit evidence with TLE provenance for external inspection."""

    differences = _orbit_differences(first, second)
    joint_indices = np.flatnonzero(differences["valid"])
    by_global_index = {int(global_index): local for local, global_index in enumerate(joint_indices)}
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "source_row", "time_utc", "tle_epoch_utc", "tle_offset_seconds",
            "astropy_error_code", "skyfield_error_code",
            "astropy_latitude_deg", "astropy_longitude_deg", "astropy_altitude_km",
            "skyfield_latitude_deg", "skyfield_longitude_deg", "skyfield_altitude_km",
            "latitude_difference_deg", "longitude_difference_deg", "altitude_difference_km",
            "surface_separation_km", "position_3d_separation_km",
        ])
        for index, timestamp in enumerate(measurements.times):
            local = by_global_index.get(index)
            values = [None] * 5 if local is None else [
                abs(differences["latitude_signed_deg"][local]),
                abs(differences["longitude_signed_deg"][local]),
                abs(differences["altitude_signed_km"][local]),
                differences["surface_distance_km"][local],
                differences["position_3d_distance_km"][local],
            ]
            tle = records[int(selection.indices[index])]
            writer.writerow([
                int(measurements.source_rows[index]), timestamp.isoformat(), tle.epoch.isoformat(),
                selection.offset_seconds[index], int(first.error_codes[index]), int(second.error_codes[index]),
                first.latitude_deg[index], first.longitude_deg[index], first.altitude_km[index],
                second.latitude_deg[index], second.longitude_deg[index], second.altitude_km[index], *values,
            ])


def validate_orbit_backends(
    measurements_path, tle_path, eop_path, output_path, limit=None,
    benchmark_output_path=None, differences_output_path=None, plots_output_dir=None,
) -> dict:
    """Validate and benchmark both orbit backends on identical inputs."""

    from .benchmark import BenchmarkRecorder, runtime_metadata, sha256_file
    from .data import load_measurements
    from .orbit import propagate
    from .orbit.diagnostic_plots import write_orbit_diagnostic_plots
    from .orbit.integrity import (
        audit_eop_coverage,
        skyfield_time_data_provenance,
        validate_sgp4_reference_vector,
    )
    from .tle import load_tle_history, select_nearest_tles

    measurements = load_measurements(measurements_path).first(limit)
    records = load_tle_history(tle_path)
    selection = select_nearest_tles(measurements.times, records)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    benchmark_output = Path(benchmark_output_path) if benchmark_output_path else output.with_name("orbit-benchmark.json")
    differences_output = Path(differences_output_path) if differences_output_path else output.with_name("orbit-differences.csv")
    benchmark_output.parent.mkdir(parents=True, exist_ok=True)
    differences_output.parent.mkdir(parents=True, exist_ok=True)
    plots_output = Path(plots_output_dir) if plots_output_dir else output.with_name("orbit-validation-plots")
    recorder = BenchmarkRecorder(
        enabled=True, sample_path=benchmark_output.with_suffix(".samples.csv")
    )
    with recorder.measure("propagate_orbit_astropy"):
        astropy_result = propagate("astropy", measurements.times, records, selection, eop_path)
    with recorder.measure("propagate_orbit_skyfield"):
        skyfield_result = propagate("skyfield", measurements.times, records, selection)
    comparison = compare_orbits(astropy_result, skyfield_result)
    raw_sgp4 = compare_raw_sgp4_wrappers(measurements.times, records, selection)
    sgp4_reference = validate_sgp4_reference_vector()
    eop_audit = audit_eop_coverage(eop_path, measurements.times)
    component_statuses = (
        comparison["consistency_status"], raw_sgp4["status"],
        sgp4_reference["status"], eop_audit["status"],
    )
    comparison["consistency_status"] = (
        "pass" if all(item == "pass" for item in component_statuses) else "fail"
    )
    diagnostic_plots = write_orbit_diagnostic_plots(
        plots_output, measurements.times, selection, astropy_result, skyfield_result
    )
    comparison.update({
        "observations": len(measurements),
        "tle_records": len(records),
        "later_tle_assignments": int(np.count_nonzero(selection.offset_seconds < 0)),
        "earlier_tle_assignments": int(np.count_nonzero(selection.offset_seconds >= 0)),
        "maximum_absolute_tle_offset_seconds": float(np.max(np.abs(selection.offset_seconds))),
        "benchmark_file": str(benchmark_output),
        "differences_file": str(differences_output),
        "benchmark_scope": (
            "Focused diagnostic stages only. Official satellite-like performance is the "
            "complete orbit-to-magnetic benchmark-suite workload."
        ),
        "inputs": {
            "measurements": {"path": str(measurements_path), "sha256": sha256_file(measurements_path)},
            "tle": {"path": str(tle_path), "sha256": sha256_file(tle_path)},
            "eop": {"path": str(eop_path), "sha256": sha256_file(eop_path)},
        },
        "runtime": runtime_metadata(),
        "raw_sgp4_wrapper_consistency": raw_sgp4,
        "sgp4_reference_vector": sgp4_reference,
        "eop_coverage": eop_audit,
        "skyfield_time_data": skyfield_time_data_provenance(),
        "diagnostic_plots": diagnostic_plots,
    })
    _write_orbit_differences(
        differences_output, measurements, records, selection, astropy_result, skyfield_result
    )
    write_comparison(output_path, comparison)
    recorder.write_json(benchmark_output)
    comparison["raw_benchmark_samples"] = str(recorder.raw_sample_path)
    write_comparison(output_path, comparison)
    return comparison


def validate_magnetic_backends(
    measurements_path, tle_path, eop_path, orbit_backend, output_path,
    benchmark_output_path, limit=None, differences_output_path=None,
) -> dict:
    """Run and benchmark both magnetic backends on the same orbit positions."""

    from .benchmark import BenchmarkRecorder, runtime_metadata, sha256_file
    from .data import load_measurements
    from .magnetic import convert_magnetic
    from .orbit import propagate
    from .tle import load_tle_history, select_nearest_tles

    measurements = load_measurements(measurements_path).first(limit)
    records = load_tle_history(tle_path)
    selection = select_nearest_tles(measurements.times, records)
    orbit = propagate(orbit_backend, measurements.times, records, selection, eop_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    benchmark_output = Path(benchmark_output_path)
    benchmark_output.parent.mkdir(parents=True, exist_ok=True)
    differences_output = (
        Path(differences_output_path) if differences_output_path
        else output.with_name("magnetic-differences.csv")
    )
    differences_output.parent.mkdir(parents=True, exist_ok=True)
    recorder = BenchmarkRecorder(
        enabled=True, sample_path=benchmark_output.with_suffix(".samples.csv")
    )
    with recorder.measure("convert_magnetic_aacgmv2"):
        aacgm = convert_magnetic("aacgmv2", measurements.times, orbit)
    with recorder.measure("convert_magnetic_apexpy"):
        apex = convert_magnetic("apexpy", measurements.times, orbit)
    comparison = compare_magnetic(aacgm, apex)
    comparison.update({
        "execution_status": "pass",
        "orbit_backend": orbit_backend,
        "orbit_valid_positions": int(np.count_nonzero(orbit.error_codes == 0)),
        "observations": len(measurements),
        "tle_records": len(records),
        "later_tle_assignments": int(np.count_nonzero(selection.offset_seconds < 0)),
        "earlier_tle_assignments": int(np.count_nonzero(selection.offset_seconds >= 0)),
        "maximum_absolute_tle_offset_seconds": float(np.max(np.abs(selection.offset_seconds))),
        "benchmark_file": str(benchmark_output),
        "differences_file": str(differences_output),
        "benchmark_scope": (
            "Focused diagnostic stages only. Official satellite-like performance is the "
            "complete orbit-to-magnetic benchmark-suite workload."
        ),
        "inputs": {
            "measurements": {"path": str(measurements_path), "sha256": sha256_file(measurements_path)},
            "tle": {"path": str(tle_path), "sha256": sha256_file(tle_path)},
            "eop": {"path": str(eop_path), "sha256": sha256_file(eop_path)},
        },
        "runtime": runtime_metadata(),
    })
    _write_magnetic_differences(differences_output, measurements, orbit, aacgm, apex)
    write_comparison(output_path, comparison)
    recorder.write_json(benchmark_output)
    comparison["raw_benchmark_samples"] = str(recorder.raw_sample_path)
    write_comparison(output_path, comparison)
    return comparison
