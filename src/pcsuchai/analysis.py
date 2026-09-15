"""Scientific summaries that share the exact plotting filters."""

from __future__ import annotations

import math

import numpy as np

from .models import MagneticResult, Measurements, OrbitResult
from .plot_config import PlotSpec, select_plot_data


def calculate_particle_weighted_centroid(
    spec: PlotSpec,
    measurements: Measurements,
    orbit: OrbitResult,
    magnetic: MagneticResult | None,
    *, allow_unavailable: bool = False,
) -> dict:
    """Calculate a particle-weighted centroid using a plot's exact mask.

    Longitude uses a circular weighted mean, avoiding the ±180-degree failure
    of the archive's arithmetic longitude average. Latitude uses an arithmetic
    weighted mean: this is not a three-dimensional spherical centroid or a
    physical estimate of the South Atlantic Anomaly's boundary.
    ``allow_unavailable`` retains a null-valued, explicitly unavailable summary
    for empty/weightless selections instead of aborting an otherwise valid job.
    Counts are nonnegative weights. Normalize before multiplication to avoid
    overflow; an overflowing total is separately unavailable. A normalized
    circular resultant at or below 64 float64 epsilons has undefined longitude
    at this numerical resolution, not an arbitrary longitude from roundoff.
    """

    selection = select_plot_data(spec, measurements, orbit, magnetic)
    mask = selection.mask
    weights = np.asarray(measurements.particle_counts[mask], dtype=float)
    def unavailable(reason: str) -> dict:
        """Retain explicit undefined-summary metadata without changing the mask."""

        if allow_unavailable:
            return {"status": "unavailable", "reason": reason,
                    "plot_name": spec.name, "coordinate_view": spec.coordinate_view,
                    "latitude_deg": None, "longitude_deg": None, "total_particle_count": None,
                    "points": int(mask.sum())}
        raise ValueError(f"plot '{spec.name}' centroid unavailable: {reason}")

    if not np.any(mask) or not np.all(np.isfinite(weights)) or not np.any(weights > 0):
        return unavailable("no positive finite particle weight in this selection")
    if np.any(weights < 0):
        return unavailable("negative particle counts are not valid centroid weights")
    latitude = selection.y[mask]
    longitude_rad = np.deg2rad(selection.x[mask])
    if not np.all(np.isfinite(latitude)) or not np.all(np.isfinite(longitude_rad)):
        return unavailable("selected centroid coordinates are non-finite")
    normalized = weights / np.max(weights)
    normalized_total = float(np.sum(normalized))
    sine = float(np.sum(normalized * np.sin(longitude_rad))) / normalized_total
    cosine = float(np.sum(normalized * np.cos(longitude_rad))) / normalized_total
    if math.hypot(sine, cosine) <= 64 * np.finfo(np.float64).eps:
        return unavailable("circular longitude mean is numerically undefined")
    longitude = (float(np.rad2deg(np.arctan2(sine, cosine))) + 180) % 360 - 180
    try:
        total = math.fsum(float(weight) for weight in weights)
    except OverflowError:
        total = None
    return {
        "status": "available",
        "plot_name": spec.name,
        "coordinate_view": spec.coordinate_view,
        "latitude_deg": float(np.sum(latitude * normalized) / normalized_total),
        "longitude_deg": float(longitude),
        "total_particle_count": total,
        "total_particle_count_status": "available" if total is not None else "overflow_float64",
        "points": int(mask.sum()),
    }
