"""Validated plot recipes and shared observation filtering."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .models import MagneticResult, Measurements, OrbitResult


MEASUREMENT_FIELDS = {
    "particle_count": ("particle_counts", "Particle counter"),
    "plasma_temperature": ("plasma_temperature", "Plasma temperature"),
    "plasma_voltage": ("plasma_voltage", "Plasma voltage"),
    "sweep_voltage": ("sweep_voltage", "Sweep voltage"),
    "plasma_current": ("plasma_current", "Plasma current"),
    "electron_density_300k": ("electron_density_300k", "Electron density 300 K"),
    "electron_density_3000k": ("electron_density_3000k", "Electron density 3000 K"),
}


def _utc(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to timezone-aware UTC."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _intervals(values: list[list[str]]) -> tuple[tuple[datetime, datetime], ...]:
    """Validate and parse a list of inclusive UTC intervals."""

    result = []
    for value in values:
        if len(value) != 2:
            raise ValueError("each time interval must contain exactly [start, end]")
        start, end = _utc(value[0]), _utc(value[1])
        if start > end:
            raise ValueError(f"time interval starts after it ends: {value}")
        result.append((start, end))
    return tuple(result)


@dataclass(frozen=True)
class PlotSpec:
    """One fully specified, reproducible image request.

    Numeric comparison fields are explicit (`gt`, `ge`, `lt`, and `le`) so the
    contradictory legacy meaning of a generic ``threshold`` cannot recur.
    """

    name: str
    plot_type: str = "map"
    variable: str = "particle_count"
    coordinate_view: str = "geographic"
    include_times: tuple[tuple[datetime, datetime], ...] = ()
    exclude_times: tuple[tuple[datetime, datetime], ...] = ()
    mlt_sector: str | None = None
    day_mlt_start: float = 6.0
    day_mlt_end: float = 18.0
    mlt_intervals: tuple[tuple[float, float], ...] = ()
    geographic_latitude_min: float | None = None
    geographic_latitude_max: float | None = None
    geographic_longitude_min: float | None = None
    geographic_longitude_max: float | None = None
    particle_gt: float | None = None
    particle_ge: float | None = None
    particle_lt: float | None = None
    particle_le: float | None = None
    value_gt: float | None = None
    value_ge: float | None = None
    value_lt: float | None = None
    value_le: float | None = None
    scale: str = "auto"
    cmap: str = "plasma"
    marker_size: float = 20.0
    width_px: int = 1200
    height_px: int = 600
    dpi: int = 100
    title: str | None = None
    extent: tuple[float, float, float, float] | None = None
    calculate_centroid: bool = False

    @classmethod
    def from_dict(cls, raw: dict) -> "PlotSpec":
        """Create a plot specification while rejecting misspelled options."""

        allowed = {field.name for field in fields(cls)}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown plot options: {', '.join(sorted(unknown))}")
        values = dict(raw)
        values["include_times"] = _intervals(values.get("include_times", []))
        values["exclude_times"] = _intervals(values.get("exclude_times", []))
        values["mlt_intervals"] = tuple(
            (float(interval[0]), float(interval[1]))
            for interval in values.get("mlt_intervals", [])
        )
        if "extent" in values:
            values["extent"] = tuple(float(item) for item in values["extent"])
        spec = cls(**values)
        spec.validate()
        return spec

    def validate(self) -> None:
        """Reject ambiguous or physically invalid plot configuration."""

        if not self.name or "/" in self.name or "\\" in self.name:
            raise ValueError("plot name must be a non-empty filename-safe label")
        if self.variable not in MEASUREMENT_FIELDS:
            raise ValueError(f"unknown measurement variable: {self.variable}")
        if self.plot_type not in ("map", "time_availability"):
            raise ValueError("plot_type must be map or time_availability")
        if self.coordinate_view not in ("geographic", "magnetic", "footpoint"):
            raise ValueError(f"unknown coordinate view: {self.coordinate_view}")
        if self.mlt_sector not in (None, "day", "night"):
            raise ValueError("mlt_sector must be day, night, or null")
        if self.scale not in ("auto", "linear", "log10"):
            raise ValueError("scale must be auto, linear, or log10")
        if self.width_px <= 0 or self.height_px <= 0 or self.dpi <= 0 or self.marker_size <= 0:
            raise ValueError("image dimensions, DPI, and marker size must be positive")
        if self.extent is not None and len(self.extent) != 4:
            raise ValueError("extent must be [longitude_min, longitude_max, latitude_min, latitude_max]")
        for hour in (self.day_mlt_start, self.day_mlt_end):
            if not 0 <= hour <= 24:
                raise ValueError("MLT sector hours must be between 0 and 24")
        for start, end in self.mlt_intervals:
            if not 0 <= start <= 24 or not 0 <= end <= 24:
                raise ValueError("MLT interval hours must be between 0 and 24")


@dataclass(frozen=True)
class PlotSelection:
    """Coordinates, colour values, and source mask selected for one plot."""

    mask: np.ndarray
    x: np.ndarray
    y: np.ndarray
    values: np.ndarray
    x_label: str
    y_label: str
    value_label: str
    scale: str


def load_plot_specs(path: str | Path) -> tuple[PlotSpec, ...]:
    """Load a plain/gzip JSON profile containing a non-empty ``plots`` list."""

    import gzip
    source = Path(path)
    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    if set(document) != {"plots"} or not isinstance(document["plots"], list):
        raise ValueError("plot configuration must contain only a 'plots' list")
    specs = tuple(PlotSpec.from_dict(item) for item in document["plots"])
    if not specs:
        raise ValueError("plot configuration contains no plots")
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("plot names must be unique")
    return specs


def plot_spec_metadata(spec: PlotSpec) -> dict:
    """Serialize every plot option for an auditable run manifest."""

    result = asdict(spec)
    result["include_times"] = [
        [start.isoformat(), end.isoformat()] for start, end in spec.include_times
    ]
    result["exclude_times"] = [
        [start.isoformat(), end.isoformat()] for start, end in spec.exclude_times
    ]
    result["mlt_intervals"] = [list(interval) for interval in spec.mlt_intervals]
    result["extent"] = list(spec.extent) if spec.extent is not None else None
    return result


def measurement_values(measurements: Measurements, variable: str) -> tuple[np.ndarray, str]:
    """Return one trusted measurement vector and its human-readable label."""

    try:
        attribute, label = MEASUREMENT_FIELDS[variable]
    except KeyError as exc:
        raise ValueError(f"unknown measurement variable: {variable}") from exc
    return np.asarray(getattr(measurements, attribute)), label


def _hour_mask(values: np.ndarray, start: float, end: float) -> np.ndarray:
    """Select a half-open MLT interval, including intervals wrapping midnight."""

    if start == end:
        return np.isfinite(values)
    if start < end:
        return (values >= start) & (values < end)
    return (values >= start) | (values < end)


def _longitude_mask(values: np.ndarray, minimum: float, maximum: float) -> np.ndarray:
    """Select a longitude range, allowing a dateline-wrapping range."""

    if minimum <= maximum:
        return (values >= minimum) & (values <= maximum)
    return (values >= minimum) | (values <= maximum)


def select_plot_data(
    spec: PlotSpec,
    measurements: Measurements,
    orbit: OrbitResult,
    magnetic: MagneticResult | None,
) -> PlotSelection:
    """Apply every configured filter and select coordinates for plotting."""

    spec.validate()
    count = len(measurements)
    if len(orbit.latitude_deg) != count:
        raise ValueError("orbit and measurement lengths differ")
    values, value_label = measurement_values(measurements, spec.variable)
    mask = (orbit.error_codes == 0) & np.isfinite(values)

    if spec.coordinate_view == "geographic":
        x, y = orbit.longitude_deg, orbit.latitude_deg
        x_label, y_label = "Geographic longitude (°)", "Geographic latitude (°)"
    else:
        if magnetic is None:
            raise ValueError(f"{spec.coordinate_view} plot requires a magnetic backend")
        mask &= magnetic.error_codes == 0
        if spec.coordinate_view == "magnetic":
            x, y = magnetic.longitude_deg, magnetic.latitude_deg
            x_label = f"{magnetic.coordinate_system} longitude (°)"
            y_label = f"{magnetic.coordinate_system} latitude (°)"
        else:
            x, y = magnetic.surface_longitude_deg, magnetic.surface_latitude_deg
            x_label, y_label = "Footpoint geographic longitude (°)", "Footpoint geographic latitude (°)"
    mask &= np.isfinite(x) & np.isfinite(y)

    timestamps = np.asarray(measurements.times, dtype=object)
    if spec.include_times:
        included = np.zeros(count, dtype=bool)
        for start, end in spec.include_times:
            included |= np.fromiter((start <= item <= end for item in timestamps), bool, count)
        mask &= included
    for start, end in spec.exclude_times:
        excluded = np.fromiter((start <= item <= end for item in timestamps), bool, count)
        mask &= ~excluded

    if spec.mlt_sector is not None or spec.mlt_intervals:
        if magnetic is None:
            raise ValueError("MLT filters require a magnetic backend")
        mlt = magnetic.local_time_hours
        mask &= np.isfinite(mlt) & (magnetic.error_codes == 0)
        if spec.mlt_sector is not None:
            day = _hour_mask(mlt, spec.day_mlt_start, spec.day_mlt_end)
            mask &= day if spec.mlt_sector == "day" else ~day
        if spec.mlt_intervals:
            selected_mlt = np.zeros(count, dtype=bool)
            for start, end in spec.mlt_intervals:
                selected_mlt |= _hour_mask(mlt, start, end)
            mask &= selected_mlt

    latitude, longitude = orbit.latitude_deg, orbit.longitude_deg
    if spec.geographic_latitude_min is not None:
        mask &= latitude >= spec.geographic_latitude_min
    if spec.geographic_latitude_max is not None:
        mask &= latitude <= spec.geographic_latitude_max
    if spec.geographic_longitude_min is not None or spec.geographic_longitude_max is not None:
        minimum = spec.geographic_longitude_min if spec.geographic_longitude_min is not None else -180.0
        maximum = spec.geographic_longitude_max if spec.geographic_longitude_max is not None else 180.0
        mask &= _longitude_mask(longitude, minimum, maximum)

    particles = measurements.particle_counts
    comparisons = (
        (spec.particle_gt, particles > (spec.particle_gt or 0)),
        (spec.particle_ge, particles >= (spec.particle_ge or 0)),
        (spec.particle_lt, particles < (spec.particle_lt or 0)),
        (spec.particle_le, particles <= (spec.particle_le or 0)),
        (spec.value_gt, values > (spec.value_gt or 0)),
        (spec.value_ge, values >= (spec.value_ge or 0)),
        (spec.value_lt, values < (spec.value_lt or 0)),
        (spec.value_le, values <= (spec.value_le or 0)),
    )
    for configured, comparison in comparisons:
        if configured is not None:
            mask &= comparison

    scale = spec.scale
    if scale == "auto":
        scale = "log10" if spec.variable.startswith("electron_density") else "linear"
    if scale == "log10":
        minimum_positive = 1.0 if spec.scale == "auto" and spec.variable.startswith(
            "electron_density"
        ) else 0.0
        mask &= values > minimum_positive

    return PlotSelection(mask, np.asarray(x), np.asarray(y), values, x_label, y_label, value_label, scale)
