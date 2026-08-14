"""Scientific summaries that share the exact plotting filters."""

from __future__ import annotations

import numpy as np

from .models import MagneticResult, Measurements, OrbitResult
from .plot_config import PlotSpec, select_plot_data


def calculate_particle_weighted_centroid(
    spec: PlotSpec,
    measurements: Measurements,
    orbit: OrbitResult,
    magnetic: MagneticResult | None,
) -> dict[str, float | int | str]:
    """Calculate a particle-weighted centroid using a plot's exact mask.

    Longitude uses a circular weighted mean, avoiding the ±180-degree failure
    of the archive's arithmetic longitude average. For the South Atlantic
    region this gives effectively the same result while remaining globally
    correct.
    """

    selection = select_plot_data(spec, measurements, orbit, magnetic)
    mask = selection.mask
    weights = np.asarray(measurements.particle_counts[mask], dtype=float)
    if not np.any(mask) or not np.all(np.isfinite(weights)) or np.sum(weights) <= 0:
        raise ValueError(f"plot '{spec.name}' has no positive finite weight for a centroid")
    latitude = selection.y[mask]
    longitude_rad = np.deg2rad(selection.x[mask])
    total = float(np.sum(weights))
    longitude = np.rad2deg(
        np.arctan2(np.sum(weights * np.sin(longitude_rad)),
                   np.sum(weights * np.cos(longitude_rad)))
    )
    return {
        "plot_name": spec.name,
        "coordinate_view": spec.coordinate_view,
        "latitude_deg": float(np.sum(latitude * weights) / total),
        "longitude_deg": float(longitude),
        "total_particle_count": total,
        "points": int(mask.sum()),
    }
