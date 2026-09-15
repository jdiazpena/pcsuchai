"""Bounded display envelopes of retained telemetry; raw samples are not pruned."""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path


def reading_elapsed(reading: dict, raw_fields: dict) -> tuple[float | None, str]:
    """Use acquisition monotonic time when its segment anchor was retained.

    Historical journals lack that anchor. Their saved sample-context elapsed
    clock remains usable, but is explicitly not the individual reading time.
    No UTC subtraction or inferred anchor disguises that historical limitation.
    """

    instant = reading.get("monotonic_seconds")
    try:
        anchor = float(raw_fields["elapsed_anchor_monotonic_seconds"])
    except (ValueError, KeyError, TypeError):
        anchor = None
    if type(instant) in (int, float) and math.isfinite(instant) and anchor is not None and math.isfinite(anchor):
        return instant - anchor, "individual_acquisition_monotonic_minus_retained_segment_anchor"
    try:
        elapsed = float(raw_fields["campaign_elapsed_seconds"])
    except (ValueError, KeyError, TypeError):
        return None, "unavailable"
    return (elapsed, "historical_sample_context_elapsed_not_individual_acquisition") if math.isfinite(elapsed) else (None, "unavailable")


def outcome_series(attempts: list[dict]) -> list[dict]:
    """Keep pair/kind/status/exclusion identities distinct at the same ordinal."""

    groups = {}
    for attempt in attempts:
        if attempt.get("worker_seconds") is None or attempt.get("attempt_number") is None:
            continue
        status = "excluded" if attempt.get("issues") else attempt["status"]
        identity = (attempt.get("pair", "unknown"), attempt["kind"], status)
        groups.setdefault(identity, []).append(attempt)
    return [{"pair": key[0], "kind": key[1], "status": key[2], "attempts": values}
            for key, values in sorted(groups.items())]


class DisplayEnvelope:
    """Keep first/last/min/max samples in progressively merged acquisition bins.

    Binning changes only the derived display, never saved observation data. Real
    timestamps and extrema survive merging. Fixed bin capacity bounds plotting
    memory independently of a multi-day telemetry timeline.
    """

    def __init__(self, maximum_bins: int = 512):
        self.maximum_bins, self.stride, self.count, self.bins = maximum_bins, 1, 0, {}

    @staticmethod
    def _merge(first: tuple, second: tuple) -> tuple:
        """Combine adjacent summaries preserving sampled extrema and endpoints."""

        return (first[0], second[1], min(first[2], second[2], key=lambda point: point[1]),
                max(first[3], second[3], key=lambda point: point[1]))

    def add(self, x: float, y: float) -> None:
        """Retain finite scalar samples with their actual acquisition coordinates."""

        if not math.isfinite(x) or not math.isfinite(y):
            return
        point = (x, y, self.count)
        identity = self.count // self.stride
        self.count += 1
        self.bins[identity] = self._merge(self.bins[identity], (point,) * 4) if identity in self.bins else (point,) * 4
        if len(self.bins) > self.maximum_bins:
            merged = {}
            for key, summary in sorted(self.bins.items()):
                index = key // 2
                merged[index] = self._merge(merged[index], summary) if index in merged else summary
            self.bins, self.stride = merged, self.stride * 2

    def points(self) -> list[tuple]:
        """Return retained samples in original acquisition order, not UTC order."""

        points = {point[2]: point for summary in self.bins.values() for point in summary}
        return [points[key] for key in sorted(points)]

    def metadata(self) -> dict:
        """Declare display reduction and the separate unchanged raw journal."""

        return {"raw_numeric_samples": self.count, "displayed_samples": len(self.points()),
                "acquisition_bin_width_samples": self.stride, "maximum_bins": self.maximum_bins,
                "method": "first_last_min_max_acquisition_bins", "raw_samples_deleted": False}


def render_report_plots(observations: str | Path, attempts: list[dict], output_dir: str | Path) -> list[dict]:
    """Plot outcomes and sensor/resource samples from saved report journals only.

    Frequency sources remain separate. Missing sensors are annotated, not drawn
    as zero. Scatter marks avoid interpolating across acquisition gaps/process
    replacements. The elapsed axis uses the saved monotonic campaign clock.
    These plots cannot establish temperature causality or a memory leak.
    """

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    destination = Path(output_dir)
    groups, elapsed_sources = {}, {}
    with gzip.open(observations, "rt", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            identity = (record["experiment_id"], record["block_path"])
            channels = groups.setdefault(identity, {})
            fields = record["raw_csv_fields"]
            for role, names in (("board", ("soc_temperature_c", "requested_frequency_hz", "observed_firmware_arm_frequency_hz")),
                                ("worker", ("rss_bytes", "pss_bytes", "uss_bytes")),
                                ("supervisor", ("rss_bytes", "pss_bytes", "uss_bytes"))):
                for name in names:
                    role_readings = record["observations"].get(role, {})
                    if not isinstance(role_readings, dict):
                        continue
                    reading = role_readings.get(name, {})
                    if not isinstance(reading, dict):
                        continue
                    if reading.get("status") == "available" and type(reading.get("value")) in (int, float):
                        elapsed, elapsed_source = reading_elapsed(reading, fields)
                        if elapsed is not None:
                            channels.setdefault((role, name), DisplayEnvelope()).add(elapsed, reading["value"])
                            elapsed_sources.setdefault(identity, set()).add(elapsed_source)
    # Also produce outcome plots for attempts with no readable telemetry.
    for attempt in attempts:
        groups.setdefault((attempt["experiment_id"], attempt["block_path"]), {})
    results = []
    for index, (identity, channels) in enumerate(sorted(groups.items()), 1):
        figure = Figure(figsize=(11, 9), dpi=100)
        FigureCanvasAgg(figure)
        axes = figure.subplots(2, 2)
        temperature, frequency, memory, outcomes = axes.flat
        for (role, name), envelope in channels.items():
            points = envelope.points()
            if not points:
                continue
            x, y = [point[0] for point in points], [point[1] for point in points]
            axis, scale = (temperature, 1) if name == "soc_temperature_c" else (frequency, 1e-6) if "frequency" in name else (memory, 1 / (1024 * 1024))
            axis.scatter(x, [value * scale for value in y], s=8, label=f"{role}: {name}")
        for axis, title, ylabel in ((temperature, "Built-in SoC temperature", "°C"),
                                    (frequency, "Requested versus firmware-observed clock", "MHz"),
                                    (memory, "Sampled worker/supervisor live memory", "MiB")):
            axis.set(title=title, xlabel="Recorded block monotonic elapsed seconds", ylabel=ylabel)
            axis.grid(alpha=0.25)
            if axis.collections:
                axis.legend(fontsize=7)
            else:
                axis.text(0.5, 0.5, "No available readings; see raw availability records", ha="center", va="center",
                          transform=axis.transAxes, fontsize=8)
        selected = [attempt for attempt in attempts if (attempt["experiment_id"], attempt["block_path"]) == identity]
        statuses = {"complete": "tab:green", "failed": "tab:red", "interrupted": "tab:orange", "excluded": "tab:purple"}
        markers = {"astropy-aacgmv2": "o", "astropy-apexpy": "s", "skyfield-aacgmv2": "^", "skyfield-apexpy": "D"}
        series = outcome_series(selected)
        for group in series:
            valid = group["attempts"]
            outcomes.scatter([attempt["attempt_number"] for attempt in valid], [attempt["worker_seconds"] for attempt in valid],
                             s=22, color=statuses.get(group["status"], "tab:gray"), marker=markers.get(group["pair"], "x"),
                             alpha=0.45 if group["kind"] == "warmup" else 0.9,
                             label=f"{group['pair']} / {group['kind']} / {group['status']} ({len(valid)})")
        missing = sum(attempt.get("worker_seconds") is None or attempt.get("attempt_number") is None for attempt in selected)
        outcomes.set(title=f"Warm-up/measured outcomes (untimed/unplaced: {missing})", xlabel="Scheduled attempt number per pair", ylabel="Worker-boundary seconds")
        outcomes.grid(alpha=0.25)
        if outcomes.collections:
            outcomes.legend(fontsize=7)
        figure.suptitle(f"Saved observations — {identity[1]}\nSampled trends, not a causal thermal or leak diagnosis", fontsize=10)
        figure.tight_layout(rect=(0, 0, 1, 0.94))
        filename = destination / f"observations-{index:04d}.png"
        figure.savefig(filename)
        figure.clear()
        results.append({"experiment_id": identity[0], "block_path": identity[1], "path": filename.name,
                        "channels": [{"role": key[0], "metric": key[1], **value.metadata()} for key, value in channels.items()],
                        "raw_source": Path(observations).name, "elapsed_sources": sorted(elapsed_sources.get(identity, set())),
                        "outcome_groups": [{key: value for key, value in group.items() if key != "attempts"} | {"count": len(group["attempts"])} for group in series]})
    return results
