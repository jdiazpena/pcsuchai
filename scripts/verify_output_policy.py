#!/usr/bin/env python3
"""Locally compare both output policies on full data and all 32 plot recipes.

    Native calculations/plot selections are hashed while still in memory, before
    either policy saves products. Outputs and measurements remain in a fresh
    directory. Storage numbers describe this PC, not Raspberry Pi performance.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pcsuchai.pipeline as pipeline
from pcsuchai.benchmark import runtime_metadata, sha256_file
from pcsuchai.benchmark_suite import _source_digest, _validate_run


def _digest(result):
    """Hash every result field with dtype/shape identity, preserving NaN bytes."""

    digest = hashlib.sha256()
    for item in fields(result):
        value = getattr(result, item.name)
        if item.name == "times":
            value = [instant.isoformat() for instant in value]
        array = np.asarray(value)
        if array.dtype.kind == "O":
            raise ValueError(f"unexpected object field in parity evidence: {item.name}")
        digest.update(json.dumps([item.name, array.dtype.str, array.shape]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def main():
    """Verify full native parity and retain actual per-policy storage inventories."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = ROOT / "outputs/verification" / f"{stamp}-output-policy"
    destination.mkdir(parents=True, exist_ok=False)
    print(f"VERIFICATION: {destination}", flush=True)
    evidence = {"classification": "local_functional_parity_and_storage_not_Pi_performance",
                "source": _source_digest(ROOT), "runtime": runtime_metadata(), "pairs": {}}
    for orbit in ("astropy", "skyfield"):
        for magnetic in ("aacgmv2", "apexpy"):
            pair = f"{orbit}-{magnetic}"
            records = {}
            for policy in ("validation", "onboard"):
                captured = {}

                def observe(name, original):
                    """Capture a digest of actual production arrays, not saved counts."""
                    def wrapped(*args, **kwargs):
                        result = original(*args, **kwargs)
                        captured.setdefault(name, []).append(_digest(result))
                        return result
                    return wrapped

                originals = {name: getattr(pipeline, name) for name in ("load_measurements", "select_nearest_tles",
                             "propagate", "convert_magnetic", "select_plot_data")}
                with patch.multiple(pipeline, **{name: observe(name, value) for name, value in originals.items()}):
                    started = time.perf_counter()
                    outputs = pipeline.run_analysis(ROOT / "data/raw/langmuir-2018-2.csv", ROOT / "data/tle/suchai1.tle",
                        destination / pair / policy, eop_path=ROOT / "data/eop/finals2000A.all", orbit_backend=orbit,
                        magnetic_backend=magnetic, plot_config_path=ROOT / "configs/plots/archive-full.json",
                        output_policy=policy, benchmark=True)
                    elapsed = time.perf_counter() - started
                checked = _validate_run(asdict(outputs), elapsed)
                files = [p for p in (destination / pair / policy).rglob("*") if p.is_file()]
                images = [outputs.particle_map_png, outputs.magnetic_particle_map_png,
                          outputs.footpoint_particle_map_png, *outputs.configured_plot_files]
                records[policy] = {"observations": outputs.observations, "captured_array_digests": captured,
                                   "image_sha256": [sha256_file(p) for p in images],
                                   "saved_product_check_passed": checked["image_validation"]["passed"],
                                   "logical_bytes": sum(p.stat().st_size for p in files), "file_count": len(files),
                                   "inventory": {p.relative_to(destination / pair / policy).as_posix(): p.stat().st_size for p in files},
                                   "wall_seconds": elapsed, "timing_scope": "local_verification_with_parity_observer"}
                print(f"{pair} {policy}: {records[policy]['logical_bytes']} bytes", flush=True)
            parity = (records["validation"]["captured_array_digests"] == records["onboard"]["captured_array_digests"]
                      and records["validation"]["image_sha256"] == records["onboard"]["image_sha256"]
                      and all(r["observations"] == 26725 and r["saved_product_check_passed"] for r in records.values()))
            evidence["pairs"][pair] = {"passed": parity, "policies": records,
                                      "storage_reduction_fraction": 1 - records["onboard"]["logical_bytes"] / records["validation"]["logical_bytes"]}
            if not parity:
                break
    evidence["passed"] = len(evidence["pairs"]) == 4 and all(item["passed"] for item in evidence["pairs"].values())
    with (destination / "verification.json").open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"passed": evidence["passed"], "report": str(destination / "verification.json")}), flush=True)
    return 0 if evidence["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
