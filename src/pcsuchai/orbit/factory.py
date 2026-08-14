"""Select orbit backends without importing unavailable optional libraries."""

from __future__ import annotations

from pathlib import Path

from ..models import OrbitResult, TLERecord, TLESelection


def propagate(
    backend: str,
    times: tuple,
    records: tuple[TLERecord, ...],
    selection: TLESelection,
    eop_path: str | Path | None = None,
) -> OrbitResult:
    """Propagate observations with the named backend.

    Backend modules are imported lazily so that a missing optional library only
    affects the backend that requires it.
    """

    if backend == "astropy":
        from .astropy_backend import propagate_astropy

        return propagate_astropy(times, records, selection, eop_path=eop_path)
    if backend == "skyfield":
        from .skyfield_backend import propagate_skyfield

        return propagate_skyfield(times, records, selection)
    raise ValueError(f"unknown orbit backend: {backend}")
