"""Deployment checks that run before any publishable benchmark session."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .benchmark import runtime_metadata


PACKAGE_FOR_BACKEND = {
    "astropy": ("astropy", "sgp4"),
    "skyfield": ("skyfield", "sgp4"),
    "aacgmv2": ("aacgmv2",),
    "apexpy": ("apexpy",),
}

# Load the modules actually used during propagation, not lazy package roots.
MODULE_FOR_ORBIT_BACKEND = {
    "astropy": ("astropy.units", "astropy.coordinates", "astropy.time",
                "astropy.utils.iers", "sgp4.api"),
    "skyfield": ("skyfield.api", "sgp4.api"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pinned_versions(path: Path) -> dict[str, str]:
    """Read simple exact pins while ignoring comments and blank lines."""

    pins = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise ValueError(f"preflight version policy requires exact pins: {line}")
        name, expected = line.split("==", 1)
        pins[name.strip().lower()] = expected.strip()
    return pins


def _add(checks: list[dict], name: str, passed: bool, detail: object, required: bool = True) -> None:
    checks.append({"name": name, "passed": bool(passed), "required": required, "detail": detail})


def _backend_smoke(name: str) -> str:
    """Check magnetic conversions and import the actual orbit runtime modules."""

    if name == "apexpy":
        import numpy as np
        from apexpy import Apex

        apex = Apex(date=2018.5)
        qlat, qlon = apex.convert(np.array([-30.0]), np.array([-60.0]), "geo", "qd", height=500.0)
        if not np.isfinite(qlat).all() or not np.isfinite(qlon).all():
            raise RuntimeError("ApexPy returned non-finite coordinates")
        return f"QD=({float(qlat[0]):.6f}, {float(qlon[0]):.6f})"
    if name == "aacgmv2":
        from datetime import datetime
        import aacgmv2

        lat, lon, _ = aacgmv2.convert_latlon(-30.0, -60.0, 500.0, datetime(2018, 7, 1), "G2A")
        if not all(map(lambda value: value == value, (lat, lon))):
            raise RuntimeError("AACGMv2 returned non-finite coordinates")
        return f"AACGM=({lat:.6f}, {lon:.6f})"
    for package in MODULE_FOR_ORBIT_BACKEND[name]:
        importlib.import_module(package)
    return "imports succeeded"


def run_preflight(
    project_root: str | Path,
    output_dir: str | Path,
    orbit_backends: tuple[str, ...] = ("astropy", "skyfield"),
    magnetic_backends: tuple[str, ...] = ("aacgmv2", "apexpy"),
    input_manifest: str | Path | None = None,
    version_policy: str | Path | None = None,
    minimum_free_bytes: int = 1_000_000_000,
    expected_python: str | None = None,
) -> dict:
    """Return a machine-readable go/no-go report for a benchmark campaign."""

    root = Path(project_root).resolve()
    destination = Path(output_dir).resolve()
    checks: list[dict] = []
    _add(checks, "python_version", sys.version_info >= (3, 11), platform.python_version())
    if expected_python is not None:
        _add(
            checks, "exact_python_version", platform.python_version() == expected_python,
            {"expected": expected_python, "actual": platform.python_version()},
        )
    _add(checks, "linux_platform", sys.platform.startswith("linux"), sys.platform)

    requested = tuple(dict.fromkeys((*orbit_backends, *magnetic_backends)))
    for backend in requested:
        if backend not in PACKAGE_FOR_BACKEND:
            _add(checks, f"backend:{backend}", False, "unknown backend")
            continue
        try:
            detail = _backend_smoke(backend)
        except Exception as exc:  # report every installation/ABI failure uniformly
            _add(checks, f"backend:{backend}", False, f"{type(exc).__name__}: {exc}")
        else:
            _add(checks, f"backend:{backend}", True, detail)

    manifest_path = Path(input_manifest) if input_manifest else root / "configs/benchmark/input-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest["files"].items():
            path = root / relative
            actual = _sha256(path) if path.is_file() else None
            _add(
                checks, f"input:{relative}", actual == expected,
                {"expected_sha256": expected, "actual_sha256": actual, "size_bytes": path.stat().st_size if path.is_file() else None},
            )
    except Exception as exc:
        _add(checks, "input_manifest", False, f"{type(exc).__name__}: {exc}")

    if version_policy is not None:
        try:
            for package, expected in _pinned_versions(Path(version_policy)).items():
                try:
                    actual = version(package)
                except PackageNotFoundError:
                    actual = None
                _add(checks, f"version:{package}", actual == expected, {"expected": expected, "actual": actual})
        except Exception as exc:
            _add(checks, "version_policy", False, f"{type(exc).__name__}: {exc}")

    try:
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".pcsuchai-write-test-", dir=destination, delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
        free_bytes = shutil.disk_usage(destination).free
        _add(checks, "output_writable", True, str(destination))
        _add(checks, "free_storage", free_bytes >= minimum_free_bytes, {"available_bytes": free_bytes, "minimum_bytes": minimum_free_bytes})
    except Exception as exc:
        _add(checks, "output_writable", False, f"{type(exc).__name__}: {exc}")

    failed = [item["name"] for item in checks if item["required"] and not item["passed"]]
    return {
        "schema_version": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not failed else "fail",
        "failed_checks": failed,
        "project_root": str(root),
        "runtime": runtime_metadata(),
        "environment": {"python_user_site_enabled": bool(sys.flags.no_user_site == 0), "pid": os.getpid()},
        "checks": checks,
    }


def write_preflight(report: dict, path: str | Path) -> None:
    """Write a preflight report atomically enough for operator diagnosis."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
