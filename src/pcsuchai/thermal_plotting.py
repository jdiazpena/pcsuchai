"""Bounded window/firmware plots reconstructed from unchanged raw report data."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from .firmware import decode_throttling_mask
from .report_plotting import DisplayEnvelope, reading_elapsed


def _elapsed(reading, fields):
    """Prefer retained segment anchors; explicitly label unrebased old clocks."""

    elapsed, source = reading_elapsed(reading, fields)
    if source == "individual_acquisition_monotonic_minus_retained_segment_anchor":
        return elapsed, source
    instant = reading.get("monotonic_seconds")
    if type(instant) in (int, float):
        return instant, "absolute_acquisition_monotonic_clock_anchor_unavailable"
    return None, "unavailable"


def render_thermal_plots(observations, analysis: dict, output_dir) -> list[dict]:
    """Show complete/partial window metrics and current/historical bit tracks.

    Each segment is a separate figure. Unknown/legacy timing is never converted
    to exposure seconds. Display envelopes are bounded; ALL raw window and
    observation samples stay retained in their compressed journals.
    """

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    output = Path(output_dir)
    groups, sources = {}, {}
    for name in ("temperature_groups", "throttling_groups"):
        for summary in analysis[name]:
            identity = (summary["experiment_id"], summary["block_path"], summary["segment_id"])
            groups.setdefault(identity, {})
    with gzip.open(output / analysis["window_journal"], "rt") as stream:
        for line in stream:
            window = json.loads(line)
            identity = (window["experiment_id"], window["block_path"], window["segment_id"])
            channels = groups.setdefault(identity, {})
            elapsed, source = _elapsed(window["samples"]["last"], window)
            if elapsed is None:
                continue
            sources.setdefault(identity, set()).add(source)
            outcome = "qualifying" if window["qualifies_low_slope_small_range"] else "partial/nonqualifying"
            for metric in ("slope_c_per_minute", "temperature_range_c"):
                value = window[metric]
                if value is not None:
                    key = (metric, window["source"], outcome)
                    channels.setdefault(key, DisplayEnvelope()).add(elapsed, value)
    with gzip.open(observations, "rt") as stream:
        for line in stream:
            record = json.loads(line)
            board = record["observations"].get("board", {})
            if not isinstance(board, dict):
                continue
            reading = board.get("throttling_flags", {})
            if not isinstance(reading, dict) or reading.get("status") != "available":
                continue
            try:
                decoded = decode_throttling_mask(reading["value"])
            except (KeyError, ValueError):
                continue
            fields = record["raw_csv_fields"]
            elapsed, source = _elapsed(reading, fields)
            if elapsed is None:
                continue
            identity = (record["experiment_id"], record["block_path"], fields.get("segment_id"))
            channels = groups.setdefault(identity, {})
            sources.setdefault(identity, set()).add(source)
            for kind in ("current", "historical"):
                for name, active in decoded[kind].items():
                    channels.setdefault((kind, name, reading.get("source")), DisplayEnvelope()).add(elapsed, float(active))
    plots = []
    for index, (identity, channels) in enumerate(sorted(groups.items(), key=lambda item: str(item[0])), 1):
        figure = Figure(figsize=(10, 10), dpi=100)
        FigureCanvasAgg(figure)
        slope, temperature_range, flags = figure.subplots(3, 1)
        flag_names = [(kind, name) for kind in ("current", "historical")
                      for name in decode_throttling_mask(0)[kind]]
        for key, envelope in channels.items():
            points = envelope.points()
            if key[0] in ("slope_c_per_minute", "temperature_range_c"):
                axis = slope if key[0] == "slope_c_per_minute" else temperature_range
                axis.scatter([point[0] for point in points], [point[1] for point in points], s=12,
                             label=f"{key[1]} / {key[2]}")
            else:
                level = flag_names.index(key[:2])
                flags.scatter([point[0] for point in points], [level + (0.15 if point[1] else -0.15) for point in points],
                              c=["tab:red" if point[1] else "tab:gray" for point in points], s=9)
        slope.axhline(analysis["policy"]["maximum_slope_c_per_minute"], color="tab:orange", linestyle="--", alpha=0.6)
        slope.axhline(-analysis["policy"]["maximum_slope_c_per_minute"], color="tab:orange", linestyle="--", alpha=0.6)
        temperature_range.axhline(analysis["policy"]["maximum_range_c"], color="tab:orange", linestyle="--", alpha=0.6)
        flags.set_yticks(range(8), [f"{kind}: {name}" for kind, name in flag_names], fontsize=7)
        flags.set_ylim(-0.5, 7.5)
        for axis, title, unit in ((slope, "Observed-span temperature window slope", "°C/min"),
                                  (temperature_range, "Observed-span temperature range", "°C"),
                                  (flags, "Sampled firmware flags: red=set, gray=clear; no continuous exposure inferred", "Bit identity")):
            axis.set(title=title, ylabel=unit)
            axis.grid(alpha=0.2)
            axis.set_xlabel("Acquisition monotonic seconds (segment-relative when anchor exists)", fontsize=8)
            if not axis.collections:
                axis.text(0.5, 0.5, "No timed readings/windows available", transform=axis.transAxes, ha="center", fontsize=8)
            elif axis is not flags:
                axis.legend(fontsize=7)
        figure.suptitle(f"Thermal observations — {identity[1]} / {identity[2]}\nExploratory window criteria; historical flags are not current states", fontsize=9)
        figure.tight_layout(rect=(0, 0, 1, 0.95))
        filename = output / f"thermal-{index:04d}.png"
        figure.savefig(filename)
        figure.clear()
        plots.append({"experiment_id": identity[0], "block_path": identity[1], "segment_id": identity[2], "path": filename.name,
                      "elapsed_sources": sorted(sources.get(identity, set())),
                      "channels": [{"identity": list(key), **envelope.metadata()} for key, envelope in channels.items()],
                      "raw_source": Path(observations).name, "window_source": analysis["window_journal"]})
    return plots
