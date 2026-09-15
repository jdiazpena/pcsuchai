"""Small saved-summary scaling charts; no models, interpolation or raw pruning."""

from __future__ import annotations

from collections import defaultdict


def render_scaling_plots(scaling, destination):
    """Plot observed full-work latency, sampled RSS and PNG output by input rows.

    Variants lacking a unique actual successful input size stay in journals and
    counts, not at an invented x=0. Curves are filled scatter points without
    fitted complexity/capacity extrapolations. Latency intervals use the existing
    independent-session bootstrap; absent intervals are never zero-width claims.
    """

    import matplotlib.pyplot as plt

    plots = []
    for number, group in enumerate(scaling["groups"], 1):
        profiles = defaultdict(list)
        for variant in group["variants"]:
            if len(variant["actual_row_counts"]) != 1 or not variant["counts"]["usable_measured"]:
                continue
            profile = variant["variant"]["plot_profile"]
            label = profile["name"] + (f" [{profile['input_sha256'][:8]}]" if profile.get("input_sha256") else "")
            # A changed rendering contract must remain visible, not a single
            # plausible-looking named profile curve.
            contracts = variant["plot_contract_ids"]
            label += f" / contract {contracts[0][:8]}" if len(contracts) == 1 else " / contract unavailable"
            profiles[label].append(variant)
        if not profiles:
            continue
        # Bound one figure's legend/layout even with many user-defined profiles.
        labels = list(profiles)
        for page in range(0, len(labels), 4):
            figure, axes = plt.subplots(3, 1, figsize=(12, 9), dpi=100, constrained_layout=True)
            for label in labels[page:page + 4]:
                variants = sorted(profiles[label], key=lambda item: item["actual_row_counts"][0])
                for metric, marker in (("worker_seconds", "o"), ("full_cycle_seconds", "s")):
                    points = [(v["actual_row_counts"][0], v["latency"][metric]["median_of_session_medians"], v) for v in variants]
                    points = [point for point in points if point[1] is not None]
                    if points:
                        artist = axes[0].scatter([p[0] for p in points], [p[1] for p in points], marker=marker,
                                                 label=f"{label} / {metric}", linewidths=0)
                        for x, y, variant in points:
                            interval = variant["latency"][metric]["uncertainty"]["intervals"].get("median_of_session_medians")
                            if interval:
                                axes[0].vlines(x, interval[0], interval[1], color=artist.get_facecolor()[0], linewidth=1)
                for axis, metric, title in ((axes[1], "sampled_peak_rss_bytes", "Observed sampled RSS maximum (bytes)"),
                                            (axes[2], "png_bytes", "Mean PNG payload per completed job (bytes)")):
                    statistic = "maximum" if metric == "sampled_peak_rss_bytes" else "mean"
                    points = [(v["actual_row_counts"][0], v["resources"][metric][statistic]) for v in variants]
                    points = [point for point in points if point[1] is not None]
                    if points:
                        axis.scatter([p[0] for p in points], [p[1] for p in points], label=label, linewidths=0)
                    axis.set_ylabel(title)
            axes[0].set_ylabel("Full-work latency (seconds)")
            for axis in axes:
                axis.set_xlabel("Actual completed input rows")
                axis.grid(alpha=.2)
                handles, legend_labels = axis.get_legend_handles_labels()
                if handles:
                    axis.legend(handles, legend_labels, fontsize=6)
                else:
                    axis.text(.5, .5, "No available saved metric", ha="center", va="center", transform=axis.transAxes)
            failed = sum(v["counts"]["failed_or_interrupted"] for v in group["variants"])
            excluded = sum(v["counts"]["excluded_measured"] for v in group["variants"])
            figure.suptitle(f"{group['device_label']} / {group['pair']} — declared scaling work\n"
                           f"Failed/interrupted={failed}; excluded={excluded}; all raw jobs retained. "
                           "No memory-capacity or scientific-utility inference.", fontsize=10)
            path = destination / f"scaling-{number:04d}-{page // 4 + 1:02d}.png"
            figure.savefig(path, format="png", metadata={"Software": "pcsuchai"})
            plt.close(figure)
            plots.append({"scaling_control_id": group["scaling_control_id"], "device_label": group["device_label"],
                          "pair": group["pair"], "path": path.name, "width_px": 1200, "height_px": 900,
                          "raw_attempts_pruned": False, "limit": "saved controlled workload summaries, not a same-work hardware ranking or capacity forecast"})
    return plots
