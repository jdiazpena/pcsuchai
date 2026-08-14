"""Read and plot the optional OMNI one-minute SYM-H reference series."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


RECORD_PATTERN = re.compile(
    r"(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+(-?\d+)\s+(-?\d+)"
)


def load_symh(path: str | Path) -> tuple[tuple[datetime, ...], np.ndarray]:
    """Extract UTC timestamps and SYM-H values from a CDAWeb text export.

    The parser intentionally tolerates arbitrary headers and broken line
    boundaries, matching the useful behaviour of the archive implementation.
    The third numeric record field is retained as SYM-H, as in that code.
    """

    content = Path(path).read_text(encoding="utf-8", errors="replace")
    records = RECORD_PATTERN.findall(content)
    if not records:
        raise ValueError(f"no SYM-H records found in {path}")
    times = tuple(
        datetime.strptime(timestamp, "%d-%m-%Y %H:%M:%S.%f").replace(tzinfo=timezone.utc)
        for timestamp, _, _ in records
    )
    values = np.asarray([int(symh) for _, _, symh in records], dtype=np.int32)
    return times, values


def plot_symh(
    times: tuple[datetime, ...],
    values: np.ndarray,
    output_path: str | Path,
    start: datetime | None = None,
    end: datetime | None = None,
    width_px: int = 1200,
    height_px: int = 600,
    dpi: int = 100,
) -> dict:
    """Plot all or an inclusive UTC interval of the SYM-H series."""

    if len(times) != len(values):
        raise ValueError("SYM-H timestamps and values have different lengths")
    mask = np.ones(len(times), dtype=bool)
    if start is not None:
        mask &= np.fromiter((item >= start for item in times), bool, len(times))
    if end is not None:
        mask &= np.fromiter((item <= end for item in times), bool, len(times))
    if not np.any(mask):
        raise ValueError("no SYM-H records remain in the requested interval")

    destination = Path(output_path)
    cache_root = destination.parent / ".cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    selected_times = np.asarray(times, dtype=object)[mask]
    selected_values = np.asarray(values)[mask]
    figure, axes = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    axes.plot(selected_times, selected_values, linewidth=0.8)
    axes.set(xlabel="UTC time", ylabel="SYM-H (nT)")
    axes.set_title(f"SYM-H — n={int(mask.sum()):,}")
    axes.grid(alpha=0.3, linewidth=0.5)
    figure.autofmt_xdate()
    figure.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=dpi, format="png", metadata={"Software": "pcsuchai"})
    plt.close(figure)
    return {
        "path": str(destination), "points_rendered": int(mask.sum()),
        "first_time_utc": min(selected_times).isoformat(),
        "last_time_utc": max(selected_times).isoformat(),
        "minimum_nt": int(np.min(selected_values)), "maximum_nt": int(np.max(selected_values)),
        "width_px": width_px, "height_px": height_px,
        "size_bytes": destination.stat().st_size,
    }
