"""Minimal, low-dependency scientific image products."""

from __future__ import annotations

import os
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import numpy as np

from .models import MagneticResult, OrbitResult
from .plot_config import PlotSelection, PlotSpec, plot_spec_metadata


def _prepare_matplotlib(destination: Path) -> None:
    """Select the headless backend and route caches beside the output."""

    cache_root = destination.parent / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
    import matplotlib

    matplotlib.use("Agg")


@lru_cache(maxsize=1)
def _land_polygons() -> tuple[np.ndarray, ...]:
    """Load bundled Natural Earth land polygons without GIS dependencies."""

    resource = files("pcsuchai.assets").joinpath("natural_earth_110m_land.npz")
    with resource.open("rb") as handle, np.load(handle) as data:
        longitude = data["longitude_deg"]
        latitude = data["latitude_deg"]
        starts = data["part_start"]
        lengths = data["part_length"]
        return tuple(
            np.column_stack((longitude[start:start + length], latitude[start:start + length]))
            for start, length in zip(starts, lengths)
        )


@lru_cache(maxsize=1)
def _country_border_lines() -> tuple[np.ndarray, ...]:
    """Load bundled Natural Earth country-boundary line segments."""

    resource = files("pcsuchai.assets").joinpath(
        "natural_earth_110m_country_borders.npz"
    )
    with resource.open("rb") as handle, np.load(handle) as data:
        longitude = data["longitude_deg"]
        latitude = data["latitude_deg"]
        starts = data["part_start"]
        lengths = data["part_length"]
        return tuple(
            np.column_stack((longitude[start:start + length], latitude[start:start + length]))
            for start, length in zip(starts, lengths)
        )


def _decorate_geographic_axes(axes, extent=(-180.0, 180.0, -90.0, 90.0)) -> None:
    """Add offline continent context and a geographic graticule."""

    from matplotlib.collections import LineCollection, PolyCollection

    land = PolyCollection(
        _land_polygons(), facecolor="#e6e2d3", edgecolor="#555555",
        linewidth=0.45, zorder=0,
    )
    axes.add_collection(land)
    borders = LineCollection(
        _country_border_lines(), colors="#777777", linewidths=0.3,
        linestyles="dotted", zorder=0.5,
    )
    axes.add_collection(borders)
    axes.set_facecolor("#dceef7")
    axes.set(xlim=extent[:2], ylim=extent[2:])
    axes.set_xticks(np.arange(-180, 181, 30))
    axes.set_yticks(np.arange(-90, 91, 30))
    axes.grid(alpha=0.3, linewidth=0.5, zorder=1)


def plot_particle_map(
    orbit: OrbitResult,
    particle_counts: np.ndarray,
    output_path: str | Path,
    threshold: float = 0.0,
    width_px: int = 1200,
    height_px: int = 600,
    dpi: int = 100,
) -> dict[str, int | float | str]:
    """Render a minimal equirectangular particle-count map.

    This first image deliberately avoids Cartopy and runtime map downloads. It
    plots recomputed WGS84 coordinates on fixed global axes with a graticule.
    The return value describes the artifact for the run manifest.
    """

    destination = Path(output_path)
    _prepare_matplotlib(destination)
    import matplotlib.pyplot as plt

    valid = (
        np.isfinite(orbit.latitude_deg)
        & np.isfinite(orbit.longitude_deg)
        & np.isfinite(particle_counts)
        & (particle_counts >= threshold)
    )
    if not np.any(valid):
        raise ValueError("no valid observations remain after particle filtering")

    figure, axes = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    _decorate_geographic_axes(axes)
    scatter = axes.scatter(
        orbit.longitude_deg[valid],
        orbit.latitude_deg[valid],
        c=particle_counts[valid],
        s=20,
        marker="o",
        cmap="plasma",
        edgecolors="none",
        linewidths=0,
        rasterized=True,
        zorder=2,
    )
    axes.set(xlabel="Geographic longitude (°)", ylabel="Geographic latitude (°)")
    axes.set_title(f"SUCHAI-1 particle counts — {orbit.backend} orbit — n={int(valid.sum()):,}")
    colorbar = figure.colorbar(scatter, ax=axes, pad=0.02)
    colorbar.set_label("Particle counter")
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, format="png", metadata={"Software": "pcsuchai"})
    plt.close(figure)
    return {
        "path": str(destination),
        "format": "png",
        "width_px": width_px,
        "height_px": height_px,
        "points_rendered": int(valid.sum()),
        "threshold": float(threshold),
        "size_bytes": destination.stat().st_size,
    }


def plot_magnetic_particle_map(
    magnetic: MagneticResult,
    particle_counts: np.ndarray,
    output_path: str | Path,
    threshold: float = 0.0,
    width_px: int = 1200,
    height_px: int = 600,
    dpi: int = 100,
) -> dict[str, int | float | str]:
    """Render particle counts in one backend's native magnetic coordinates."""

    destination = Path(output_path)
    _prepare_matplotlib(destination)
    import matplotlib.pyplot as plt

    valid = (
        (magnetic.error_codes == 0)
        & np.isfinite(magnetic.latitude_deg)
        & np.isfinite(magnetic.longitude_deg)
        & np.isfinite(particle_counts)
        & (particle_counts >= threshold)
    )
    if not np.any(valid):
        raise ValueError("no valid magnetic observations remain after particle filtering")

    figure, axes = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    scatter = axes.scatter(
        magnetic.longitude_deg[valid], magnetic.latitude_deg[valid],
        c=particle_counts[valid], s=20, marker="o", cmap="plasma",
        edgecolors="none", linewidths=0, rasterized=True,
    )
    axes.set(
        xlim=(-180, 180), ylim=(-90, 90),
        xlabel=f"{magnetic.coordinate_system} longitude (°)",
        ylabel=f"{magnetic.coordinate_system} latitude (°)",
    )
    axes.set_xticks(np.arange(-180, 181, 30))
    axes.set_yticks(np.arange(-90, 91, 30))
    axes.grid(alpha=0.3, linewidth=0.5)
    axes.set_title(f"SUCHAI-1 particle counts — {magnetic.backend} — n={int(valid.sum()):,}")
    colorbar = figure.colorbar(scatter, ax=axes, pad=0.02)
    colorbar.set_label("Particle counter")
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, format="png", metadata={"Software": "pcsuchai"})
    plt.close(figure)
    return {
        "path": str(destination), "format": "png", "width_px": width_px,
        "height_px": height_px, "points_rendered": int(valid.sum()),
        "threshold": float(threshold), "size_bytes": destination.stat().st_size,
        "coordinate_system": magnetic.coordinate_system,
    }


def plot_footpoint_particle_map(
    magnetic: MagneticResult,
    particle_counts: np.ndarray,
    output_path: str | Path,
    threshold: float = 0.0,
    width_px: int = 1200,
    height_px: int = 600,
    dpi: int = 100,
) -> dict[str, int | float | str]:
    """Render model-mapped zero-height footpoints on a geographic map."""

    destination = Path(output_path)
    _prepare_matplotlib(destination)
    import matplotlib.pyplot as plt

    valid = (
        (magnetic.error_codes == 0)
        & np.isfinite(magnetic.surface_latitude_deg)
        & np.isfinite(magnetic.surface_longitude_deg)
        & np.isfinite(particle_counts)
        & (particle_counts >= threshold)
    )
    if not np.any(valid):
        raise ValueError("no valid footpoints remain after particle filtering")

    figure, axes = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    _decorate_geographic_axes(axes)
    scatter = axes.scatter(
        magnetic.surface_longitude_deg[valid], magnetic.surface_latitude_deg[valid],
        c=particle_counts[valid], s=20, marker="o", cmap="plasma",
        edgecolors="none", linewidths=0, rasterized=True, zorder=2,
    )
    axes.set(
        xlabel="Footpoint geographic longitude (°)",
        ylabel="Footpoint geographic latitude (°)",
    )
    axes.set_title(
        f"SUCHAI-1 particle counts — {magnetic.backend} surface mapping — n={int(valid.sum()):,}"
    )
    colorbar = figure.colorbar(scatter, ax=axes, pad=0.02)
    colorbar.set_label("Particle counter")
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, format="png", metadata={"Software": "pcsuchai"})
    plt.close(figure)
    return {
        "path": str(destination), "format": "png", "width_px": width_px,
        "height_px": height_px, "points_rendered": int(valid.sum()),
        "threshold": float(threshold), "size_bytes": destination.stat().st_size,
        "magnetic_backend": magnetic.backend, "coordinate_system": "geographic_footpoint",
    }


def plot_configured_map(
    spec: PlotSpec,
    selection: PlotSelection,
    output_path: str | Path,
) -> dict[str, int | float | str]:
    """Render one fully filtered plot specification as a headless PNG."""

    destination = Path(output_path)
    _prepare_matplotlib(destination)
    import matplotlib.pyplot as plt

    mask = selection.mask
    if not np.any(mask):
        raise ValueError(f"plot '{spec.name}' has no observations after filtering")
    colour = selection.values[mask]
    colour_label = selection.value_label
    if selection.scale == "log10":
        colour = np.log10(colour)
        colour_label = f"log10({colour_label})"

    figure, axes = plt.subplots(
        figsize=(spec.width_px / spec.dpi, spec.height_px / spec.dpi), dpi=spec.dpi
    )
    if spec.coordinate_view in ("geographic", "footpoint"):
        extent = spec.extent or (-180.0, 180.0, -90.0, 90.0)
        _decorate_geographic_axes(axes, extent)
    else:
        extent = spec.extent or (-180.0, 180.0, -90.0, 90.0)
        axes.set(xlim=extent[:2], ylim=extent[2:])
        axes.set_xticks(np.arange(-180, 181, 30))
        axes.set_yticks(np.arange(-90, 91, 30))
        axes.grid(alpha=0.3, linewidth=0.5)
    scatter = axes.scatter(
        selection.x[mask], selection.y[mask], c=colour, cmap=spec.cmap,
        s=spec.marker_size, marker="o", edgecolors="none", linewidths=0,
        rasterized=True, zorder=2,
    )
    axes.set(xlabel=selection.x_label, ylabel=selection.y_label)
    axes.set_title(spec.title or f"{spec.name.replace('_', ' ')} — n={int(mask.sum()):,}")
    colorbar = figure.colorbar(scatter, ax=axes, pad=0.02)
    colorbar.set_label(colour_label)
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=spec.dpi, format="png", metadata={"Software": "pcsuchai"})
    plt.close(figure)
    return {
        "path": str(destination), "format": "png", "width_px": spec.width_px,
        "height_px": spec.height_px, "points_rendered": int(mask.sum()),
        "size_bytes": destination.stat().st_size, "variable": spec.variable,
        "coordinate_view": spec.coordinate_view, "scale": selection.scale,
        "value_min": float(np.min(selection.values[mask])),
        "value_max": float(np.max(selection.values[mask])), "spec": plot_spec_metadata(spec),
    }


def plot_time_availability(
    spec: PlotSpec,
    selection: PlotSelection,
    times: tuple,
    output_path: str | Path,
) -> dict[str, int | float | str]:
    """Render filled observation markers against UTC time to expose data gaps."""

    destination = Path(output_path)
    _prepare_matplotlib(destination)
    import matplotlib.pyplot as plt

    mask = selection.mask
    if not np.any(mask):
        raise ValueError(f"plot '{spec.name}' has no observations after filtering")
    selected_times = np.asarray(times, dtype=object)[mask]
    figure, axes = plt.subplots(
        figsize=(spec.width_px / spec.dpi, spec.height_px / spec.dpi), dpi=spec.dpi
    )
    axes.scatter(
        selected_times, np.ones(int(mask.sum())), s=spec.marker_size, marker="o",
        facecolors="#3a60b8", edgecolors="none", linewidths=0, rasterized=True,
    )
    axes.set_yticks([])
    axes.set_xlabel("UTC observation time")
    axes.grid(axis="x", alpha=0.3, linewidth=0.5)
    axes.set_title(spec.title or f"{spec.name.replace('_', ' ')} — n={int(mask.sum()):,}")
    figure.autofmt_xdate()
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=spec.dpi, format="png", metadata={"Software": "pcsuchai"})
    plt.close(figure)
    return {
        "path": str(destination), "format": "png", "width_px": spec.width_px,
        "height_px": spec.height_px, "points_rendered": int(mask.sum()),
        "size_bytes": destination.stat().st_size, "variable": spec.variable,
        "coordinate_view": spec.coordinate_view, "plot_type": "time_availability",
        "first_time_utc": min(selected_times).isoformat(),
        "last_time_utc": max(selected_times).isoformat(),
        "spec": plot_spec_metadata(spec),
    }
