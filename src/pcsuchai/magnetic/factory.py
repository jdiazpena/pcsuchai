"""Lazy selection of magnetic-coordinate implementations."""

from __future__ import annotations

from ..models import MagneticResult, OrbitResult


def convert_magnetic(backend: str, times: tuple, orbit: OrbitResult) -> MagneticResult:
    """Convert geodetic orbit positions with the requested magnetic backend.

    Imports are deliberately lazy: a missing ApexPy installation cannot stop
    AACGMv2 processing, and a missing AACGMv2 installation cannot stop ApexPy.
    """

    if backend == "aacgmv2":
        from .aacgm_backend import convert_aacgmv2

        return convert_aacgmv2(times, orbit)
    if backend == "apexpy":
        from .apex_backend import convert_apexpy

        return convert_apexpy(times, orbit)
    raise ValueError(f"unknown magnetic backend: {backend}")
