"""Repeated clean-process diagnostic benchmark for orbit implementations."""

from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import runtime_metadata, sha256_file, system_snapshot
from .benchmark_suite import _source_digest, _statistics
from .run_lock import inherited_lock_fds, serialized_run


@serialized_run
def run_orbit_benchmark(
    output_dir: str | Path,
    project_root: str | Path,
    measurements: str | Path,
    tle: str | Path,
    eop: str | Path,
    repeats: int = 5,
    warmups: int = 1,
    seed: int = 1729,
    limit: int | None = None,
    timeout_seconds: float = 7200.0,
) -> dict:
    """Benchmark both complete orbit-only diagnostic paths in clean processes."""

    if repeats < 2 or warmups < 0:
        raise ValueError("orbit benchmark requires at least two repeats and nonnegative warmups")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    root = Path(project_root).resolve()
    paths = {"measurements": Path(measurements), "tle": Path(tle), "eop": Path(eop)}
    for name, path in paths.items():
        if not path.is_file():
            raise ValueError(f"missing orbit benchmark input {name}: {path}")
    report = {
        "schema_version": 1, "status": "running", "official": False,
        "workload_classification": "diagnostic_orbit_only",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_metadata(), "source": _source_digest(root),
        "settings": {"repeats": repeats, "warmups": warmups, "seed": seed, "limit": limit, "timeout_seconds": timeout_seconds},
        "inputs": {name: {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size} for name, path in paths.items()},
        "execution_order": [],
        "backends": {name: {"runs": []} for name in ("astropy", "skyfield")},
    }
    checkpoint = destination / "orbit-benchmark.checkpoint.json"

    def write_checkpoint() -> None:
        checkpoint.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def command(backend: str, run_dir: Path) -> list[str]:
        result = [
            sys.executable, "-m", "pcsuchai", "analyze",
            "--measurements", str(paths["measurements"]), "--tle", str(paths["tle"]),
            "--eop", str(paths["eop"]), "--output-dir", str(run_dir),
            "--orbit-backend", backend, "--magnetic-backend", "none", "--benchmark",
        ]
        if limit is not None:
            result.extend(("--limit", str(limit)))
        return result

    def execute(backend: str, run_dir: Path) -> tuple[dict, float, str]:
        exact = command(backend, run_dir)
        started = time.perf_counter()
        child = subprocess.run(
            exact, capture_output=True, text=True, timeout=timeout_seconds,
            check=False, env=child_environment,
            pass_fds=inherited_lock_fds(child_environment),
        )
        elapsed = time.perf_counter() - started
        if child.returncode:
            raise RuntimeError(f"orbit benchmark child failed: {' '.join(exact)}\n{child.stderr[-4000:]}")
        return json.loads(child.stdout), elapsed, child.stderr

    rng = random.Random(seed)
    child_environment = os.environ.copy()
    child_environment["PYTHONPATH"] = str(root / "src") + (
        os.pathsep + child_environment["PYTHONPATH"] if child_environment.get("PYTHONPATH") else ""
    )
    write_checkpoint()
    for round_index in range(warmups):
        order = ["astropy", "skyfield"]
        rng.shuffle(order)
        for backend in order:
            print(f"[orbit warmup {round_index + 1}/{warmups}] {backend}", file=sys.stderr, flush=True)
            run_dir = destination / "warmups" / f"{round_index + 1:02d}-{backend}"
            execute(backend, run_dir)
            report["execution_order"].append({"kind": "warmup", "round": round_index + 1, "backend": backend, "command": command(backend, run_dir)})
            write_checkpoint()

    for round_index in range(repeats):
        order = ["astropy", "skyfield"]
        rng.shuffle(order)
        for backend in order:
            print(f"[orbit measured {round_index + 1}/{repeats}] {backend}", file=sys.stderr, flush=True)
            run_dir = destination / "runs" / f"{round_index + 1:02d}-{backend}"
            before = system_snapshot()
            outputs, elapsed, stderr = execute(backend, run_dir)
            stages = json.loads(Path(outputs["benchmark_json"]).read_text(encoding="utf-8"))
            propagation = next(item for item in stages if item["stage"] == "propagate_orbit")
            run = {
                "round": round_index + 1, "external_wall_seconds": elapsed,
                "propagation_stage": propagation, "all_stages": stages,
                "positions_csv": {"path": outputs["positions_csv"], "sha256": sha256_file(outputs["positions_csv"]), "size_bytes": Path(outputs["positions_csv"]).stat().st_size},
                "map_png": {"path": outputs["particle_map_png"], "sha256": sha256_file(outputs["particle_map_png"]), "size_bytes": Path(outputs["particle_map_png"]).stat().st_size},
                "system_before": before, "system_after": system_snapshot(),
                "command": command(backend, run_dir), "stderr": stderr,
            }
            report["backends"][backend]["runs"].append(run)
            report["execution_order"].append({"kind": "measured", "round": round_index + 1, "backend": backend, "command": run["command"]})
            write_checkpoint()

    for backend, backend_report in report["backends"].items():
        runs = backend_report["runs"]
        hashes = [item["positions_csv"]["sha256"] for item in runs]
        fields = (
            "wall_seconds", "process_cpu_seconds", "process_user_seconds",
            "process_system_seconds", "peak_rss_bytes", "peak_threads",
            "minor_page_faults", "major_page_faults", "temperature_max_c",
            "cpu_frequency_min_mhz", "cpu_frequency_max_mhz",
        )
        backend_report["positions_repeat_consistent"] = len(set(hashes)) == 1
        backend_report["positions_sha256"] = hashes
        backend_report["summary"] = {
            "external_wall_seconds": _statistics([item["external_wall_seconds"] for item in runs]),
            "propagation_stage": {
                field: _statistics([float(item["propagation_stage"][field]) for item in runs if item["propagation_stage"].get(field) is not None])
                for field in fields
                if any(item["propagation_stage"].get(field) is not None for item in runs)
            },
        }

    report["scientific_outputs_consistent"] = all(
        item["positions_repeat_consistent"] for item in report["backends"].values()
    )
    report["status"] = "complete" if report["scientific_outputs_consistent"] else "failed"
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    csv_path = destination / "orbit-benchmark-summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["backend", "scope", "metric", "mean", "median", "standard_deviation", "minimum", "maximum", "p95"])
        for backend, backend_report in report["backends"].items():
            for scope, metrics in backend_report["summary"].items():
                if scope == "external_wall_seconds":
                    writer.writerow([backend, "whole_orbit_diagnostic_process", scope, *[metrics[key] for key in ("mean", "median", "standard_deviation", "minimum", "maximum", "p95")]])
                else:
                    for metric, values in metrics.items():
                        writer.writerow([backend, scope, metric, *[values[key] for key in ("mean", "median", "standard_deviation", "minimum", "maximum", "p95")]])
    report["summary_csv"] = {"path": str(csv_path), "sha256": sha256_file(csv_path), "size_bytes": csv_path.stat().st_size}
    report_path = destination / "orbit-benchmark.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
