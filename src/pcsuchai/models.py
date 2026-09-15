"""Typed data containers shared by pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class Measurements:
    """Trusted instrument products loaded from the tab-separated source file.

    Times are timezone-aware UTC datetimes. Numeric arrays preserve source row
    order and duplicates; no previously derived geographic columns are loaded.
    """

    times: tuple[datetime, ...]
    particle_counts: np.ndarray
    plasma_temperature: np.ndarray
    plasma_voltage: np.ndarray
    sweep_voltage: np.ndarray
    plasma_current: np.ndarray
    electron_density_300k: np.ndarray
    electron_density_3000k: np.ndarray
    headers: tuple[str, ...]
    source_rows: np.ndarray

    def __len__(self) -> int:
        """Return the number of observations."""

        return len(self.times)

    def first(self, count: int | None) -> "Measurements":
        """Return the first *count* observations, or this object when unset."""

        if count is None or count >= len(self):
            return self
        if count <= 0:
            raise ValueError("count must be positive")
        return Measurements(
            times=self.times[:count],
            particle_counts=self.particle_counts[:count],
            plasma_temperature=self.plasma_temperature[:count],
            plasma_voltage=self.plasma_voltage[:count],
            sweep_voltage=self.sweep_voltage[:count],
            plasma_current=self.plasma_current[:count],
            electron_density_300k=self.electron_density_300k[:count],
            electron_density_3000k=self.electron_density_3000k[:count],
            headers=self.headers[:count],
            source_rows=self.source_rows[:count],
        )


@dataclass(frozen=True)
class TLERecord:
    """One validated two-line element set and its UTC epoch."""

    line1: str
    line2: str
    epoch: datetime
    satellite_number: str


@dataclass(frozen=True)
class TLESelection:
    """Nearest-TLE assignment for each observation.

    ``offset_seconds`` is observation time minus TLE epoch. Negative values
    therefore identify a later (future relative to the observation) TLE.
    """

    indices: np.ndarray
    offset_seconds: np.ndarray


@dataclass(frozen=True)
class OrbitResult:
    """Geodetic WGS84 positions returned by an orbit backend.

    Latitude and longitude are degrees. Altitude is kilometres above the WGS84
    ellipsoid. Invalid propagations are represented by NaN values and a nonzero
    error code.
    """

    latitude_deg: np.ndarray
    longitude_deg: np.ndarray
    altitude_km: np.ndarray
    error_codes: np.ndarray
    backend: str


@dataclass(frozen=True)
class MagneticResult:
    """Native magnetic coordinates returned by one magnetic model.

    Magnetic latitude and longitude are degrees and magnetic local time is
    hours. ``surface_*`` is the geographic location obtained by mapping the
    observation to zero-kilometre model height (AACGM geocentric reference
    height; ApexPy geodetic height). Returned geodetic altitude is retained
    separately; ``mapping_error_deg`` is unavailable/NaN for AACGM, whose
    inverse API returns altitude rather than an angular residual.
    The two supported backends use
    different coordinate definitions, identified by ``coordinate_system``;
    their numeric coordinates are not expected to be identical.
    """

    latitude_deg: np.ndarray
    longitude_deg: np.ndarray
    local_time_hours: np.ndarray
    surface_latitude_deg: np.ndarray
    surface_longitude_deg: np.ndarray
    mapping_error_deg: np.ndarray
    error_codes: np.ndarray
    backend: str
    coordinate_system: str
    surface_altitude_km: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=float))
