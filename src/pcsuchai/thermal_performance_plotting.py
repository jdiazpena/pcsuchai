"""Bounded-display job latency versus sampled context temperature, not causality."""

import gzip
import json

from .report_plotting import DisplayEnvelope
from .thermal_performance import _finite


def render_thermal_performance_plots(journal, destination):
    """Render separate cohorts/sensor channels, retaining raw missingness elsewhere.

    Dual envelopes retain display extrema on both axes plus first/last samples.
    The full point journal is never reduced or rewritten by plotting.
    """

    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    groups = {}
    with gzip.open(journal, "rt", encoding="utf-8") as source:
        for ordinal, line in enumerate(source):
            point = json.loads(line)
            identity = tuple(point[key] for key in ("cohort_id", "device_label", "pair", "source", "scope", "unit"))
            group = groups.setdefault(identity, {"series": {}, "missing_temperature": 0, "jobs": 0})
            group["jobs"] += 1
            temperature = point["sampled_temperature"]["mean"]
            if not _finite(temperature):
                group["missing_temperature"] += 1
                continue
            status = point["status"] if point["status"] != "complete" else "complete" if point["scientifically_usable"] else "excluded"
            for metric in ("worker_seconds", "full_cycle_seconds"):
                value = point[metric]
                if not _finite(value) or value <= 0:
                    continue
                channels = group["series"].setdefault((metric, point["kind"], status), (DisplayEnvelope(), DisplayEnvelope()))
                channels[0].add(temperature, value)
                channels[1].add(value, temperature)
    results = []
    for index, (identity, group) in enumerate(sorted(groups.items(), key=lambda item: str(item[0])), 1):
        figure = Figure(figsize=(10, 5), dpi=100)
        FigureCanvasAgg(figure)
        axes = figure.subplots(1, 2)
        for axis, metric in zip(axes, ("worker_seconds", "full_cycle_seconds")):
            for (name, kind, status), channels in group["series"].items():
                if name != metric:
                    continue
                direct = {(sample[2], sample[0], sample[1]) for sample in channels[0].points()}
                direct.update((sample[2], sample[1], sample[0]) for sample in channels[1].points())
                color = "tab:gray" if kind == "warmup" and status == "complete" else {"complete": "tab:green", "failed": "tab:red", "interrupted": "tab:orange", "excluded": "tab:purple"}.get(status, "black")
                axis.scatter([sample[1] for sample in direct], [sample[2] for sample in direct], s=16, color=color,
                             edgecolors="none", label=f"{kind} / {status}")
            axis.set(xlabel="Mean sampled job-context SoC temperature (°C)", ylabel="seconds", title=metric.replace("_", " "))
            axis.grid(alpha=.25)
            if axis.collections:
                axis.legend(fontsize=8)
            else:
                axis.text(.5, .5, "No paired available temperature/positive latency", transform=axis.transAxes, ha="center", fontsize=8)
        figure.suptitle(f"{identity[1]} / {identity[2]}\nObserved context association, not causal thermal dependence", fontsize=10)
        figure.tight_layout(rect=(0, 0, 1, .9))
        path = destination / f"thermal-performance-{index:04d}.png"
        figure.savefig(path)
        figure.clear()
        results.append({"cohort_id": identity[0], "device_label": identity[1], "pair": identity[2], "source": identity[3],
                        "scope": identity[4], "unit": identity[5], "path": path.name, "job_contexts": group["jobs"],
                        "missing_temperature_contexts": group["missing_temperature"], "raw_points_pruned": False,
                        "display": "dual bounded envelopes preserving extrema of both axes"})
    return results
