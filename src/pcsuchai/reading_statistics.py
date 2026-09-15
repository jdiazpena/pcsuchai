"""Constant-memory scalar trends using original acquisition clocks/statuses."""

from __future__ import annotations

import math
from collections import Counter


class ReadingTrend:
    """Keep descriptive moments/endpoints, never the complete sample timeline.

    Callers separate role/source/unit/process/segment. A slope alone establishes
    neither a leak nor thermal causality. Raw samples remain in their journals.
    """

    def __init__(self):
        """Initialize availability, extrema and online centred-regression state."""

        self.statuses = Counter()
        self.count = 0
        self.first = self.last = self.minimum = self.maximum = None
        self.origin = None
        self.mean_x = self.mean_y = self.sxx = self.sxy = 0.0
        self.maximum_gap_seconds = 0.0
        self.clock_regressions = 0

    def add(self, reading: dict) -> None:
        """Preserve acquisition failures; unavailable zero is not a measurement."""

        self.statuses[str(reading.get("status", "unknown"))] += 1
        value, instant = reading.get("value"), reading.get("monotonic_seconds")
        if reading.get("status") != "available" or type(value) not in (int, float) or type(instant) not in (int, float):
            return
        if not math.isfinite(value) or not math.isfinite(instant):
            self.statuses["malformed_nonfinite"] += 1
            return
        point = {"value": value, "monotonic_seconds": instant, "captured_utc": reading.get("captured_utc")}
        if self.first is None:
            self.first, self.origin = point, instant
        if self.last is not None:
            gap = instant - self.last["monotonic_seconds"]
            self.maximum_gap_seconds = max(self.maximum_gap_seconds, gap)
            self.clock_regressions += gap < 0
        self.last = point
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.count += 1
        x = instant - self.origin
        dx, dy = x - self.mean_x, value - self.mean_y
        self.mean_x += dx / self.count
        self.mean_y += dy / self.count
        self.sxx += dx * (x - self.mean_x)
        self.sxy += dx * (value - self.mean_y)

    def report(self) -> dict:
        """Expose genuine gaps/regressions and unavailable one-point slopes."""

        elapsed = self.last["monotonic_seconds"] - self.first["monotonic_seconds"] if self.count else None
        return {"availability_counts": dict(self.statuses), "numeric_sample_count": self.count,
                "first": self.first, "last": self.last, "minimum": self.minimum, "maximum": self.maximum,
                "mean": self.mean_y if self.count else None,
                "observed_span_seconds": elapsed, "maximum_gap_seconds": self.maximum_gap_seconds if self.count > 1 else None,
                "clock_regressions": self.clock_regressions,
                "linear_slope_per_second": self.sxy / self.sxx if self.sxx > 0 and not self.clock_regressions else None,
                "interpretation": "descriptive sampled live/cumulative state; no automatic leak/plateau/causality diagnosis"}
