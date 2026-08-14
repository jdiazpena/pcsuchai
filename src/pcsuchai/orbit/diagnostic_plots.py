"""Orbit-specific scientific validation plots, rendered entirely offline."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..models import OrbitResult, TLESelection
from ..plotting import _decorate_geographic_axes, _prepare_matplotlib


def _save(figure, path: Path, points: int, kind: str) -> dict:
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=100, format="png", metadata={"Software": "pcsuchai"})
    import matplotlib.pyplot as plt

    plt.close(figure)
    return {"path": str(path), "kind": kind, "points": points, "size_bytes": path.stat().st_size}


def write_orbit_diagnostic_plots(
    output_dir: str | Path,
    times: tuple,
    selection: TLESelection,
    astropy_result: OrbitResult,
    skyfield_result: OrbitResult,
) -> list[dict]:
    """Write maps and time-series that expose orbit agreement and TLE coverage."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    _prepare_matplotlib(destination / "placeholder.png")
    import matplotlib.pyplot as plt

    valid = (astropy_result.error_codes == 0) & (skyfield_result.error_codes == 0)
    if not np.any(valid):
        raise ValueError("orbit diagnostic plots require jointly valid positions")
    selected_times = np.asarray(times, dtype=object)[valid]
    lat_difference = np.abs(astropy_result.latitude_deg[valid] - skyfield_result.latitude_deg[valid])
    lon_difference = np.abs(
        (astropy_result.longitude_deg[valid] - skyfield_result.longitude_deg[valid] + 180.0) % 360.0 - 180.0
    )
    altitude_difference_m = 1000.0 * np.abs(
        astropy_result.altitude_km[valid] - skyfield_result.altitude_km[valid]
    )
    lat1, lat2 = np.deg2rad(astropy_result.latitude_deg[valid]), np.deg2rad(skyfield_result.latitude_deg[valid])
    dlon = np.deg2rad(
        (astropy_result.longitude_deg[valid] - skyfield_result.longitude_deg[valid] + 180.0) % 360.0 - 180.0
    )
    haversine = np.sin((lat1 - lat2) / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    surface_separation_m = 2.0 * 6371.0088 * 1000.0 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
    artifacts = []

    figure, axes = plt.subplots(figsize=(12, 6), dpi=100)
    _decorate_geographic_axes(axes)
    scatter = axes.scatter(
        astropy_result.longitude_deg[valid], astropy_result.latitude_deg[valid],
        c=surface_separation_m, s=8, marker="o", edgecolors="none", linewidths=0,
        cmap="viridis", rasterized=True, zorder=2,
    )
    axes.set(xlabel="Geographic longitude (°)", ylabel="Geographic latitude (°)", title="Astropy–Skyfield surface separation")
    figure.colorbar(scatter, ax=axes, pad=0.02).set_label("Surface separation (m)")
    artifacts.append(_save(figure, destination / "01-separation-map.png", int(valid.sum()), "separation_map"))

    figure, axes = plt.subplots(3, 1, figsize=(12, 8), dpi=100, sharex=True)
    for axis, values, label in zip(
        axes, (lat_difference, lon_difference, altitude_difference_m),
        ("|Δ latitude| (°)", "|Δ longitude| (°)", "|Δ altitude| (m)"),
    ):
        axis.scatter(selected_times, values, s=4, marker="o", facecolors="#275dad", edgecolors="none", linewidths=0, rasterized=True)
        axis.set_ylabel(label)
        axis.grid(alpha=0.3, linewidth=0.5)
    axes[-1].set_xlabel("UTC observation time")
    axes[0].set_title("Orbit-backend differences versus time")
    figure.autofmt_xdate()
    artifacts.append(_save(figure, destination / "02-differences-vs-time.png", int(valid.sum()), "differences_time"))

    figure, axes = plt.subplots(figsize=(12, 5), dpi=100)
    axes.plot(selected_times, astropy_result.altitude_km[valid], linewidth=0.7, label="Astropy")
    axes.plot(selected_times, skyfield_result.altitude_km[valid], linewidth=0.7, alpha=0.75, label="Skyfield")
    axes.set(xlabel="UTC observation time", ylabel="WGS84 ellipsoidal altitude (km)", title="Recomputed SUCHAI-1 altitude")
    axes.grid(alpha=0.3, linewidth=0.5)
    axes.legend()
    figure.autofmt_xdate()
    artifacts.append(_save(figure, destination / "03-altitude-vs-time.png", int(valid.sum()), "altitude_time"))

    figure, axes = plt.subplots(figsize=(12, 5), dpi=100)
    offsets_hours = selection.offset_seconds / 3600.0
    axes.scatter(times, offsets_hours, s=5, marker="o", c=np.abs(offsets_hours), cmap="plasma", edgecolors="none", linewidths=0, rasterized=True)
    axes.axhline(0.0, color="black", linewidth=0.7)
    axes.set(xlabel="UTC observation time", ylabel="Observation − selected TLE epoch (hours)", title="Nearest-TLE assignment age and direction")
    axes.grid(alpha=0.3, linewidth=0.5)
    figure.autofmt_xdate()
    artifacts.append(_save(figure, destination / "04-tle-offset-vs-time.png", len(times), "tle_offset_time"))

    figure, axes = plt.subplots(1, 3, figsize=(12, 4), dpi=100)
    for axis, values, label in zip(
        axes, (lat_difference, lon_difference, altitude_difference_m),
        ("|Δ latitude| (°)", "|Δ longitude| (°)", "|Δ altitude| (m)"),
    ):
        axis.hist(values, bins=60, color="#3a60b8", edgecolor="none")
        axis.set_xlabel(label)
        axis.set_ylabel("Observations")
        axis.grid(alpha=0.2, linewidth=0.5)
    figure.suptitle("Orbit-backend difference distributions")
    artifacts.append(_save(figure, destination / "05-difference-distributions.png", int(valid.sum()), "difference_histograms"))
    return artifacts
