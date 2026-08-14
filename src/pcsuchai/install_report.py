"""Machine-readable evidence for a native Raspberry Pi installation."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import runtime_metadata, sha256_file


def create_installation_report(apex_wheel: str | Path | None = None) -> dict:
    """Describe the interpreter, Apex native extension, and cached wheel."""

    import apexpy

    package_dir = Path(apexpy.__file__).resolve().parent
    extensions = sorted(package_dir.glob("fortranapex*.so"))
    extension_records = []
    for extension in extensions:
        dependency_result = subprocess.run(
            ["ldd", str(extension)], capture_output=True, text=True, timeout=10, check=False
        )
        extension_records.append({
            "path": str(extension), "size_bytes": extension.stat().st_size,
            "sha256": sha256_file(extension), "ldd_return_code": dependency_result.returncode,
            "ldd": dependency_result.stdout, "ldd_stderr": dependency_result.stderr,
            "missing_dependency": "not found" in dependency_result.stdout,
        })
    wheel_record = None
    if apex_wheel is not None:
        wheel = Path(apex_wheel).resolve()
        wheel_record = {
            "path": str(wheel), "size_bytes": wheel.stat().st_size,
            "sha256": sha256_file(wheel),
        }
    return {
        "schema_version": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": runtime_metadata(),
        "apexpy_package": str(package_dir),
        "apexpy_extensions": extension_records,
        "apexpy_wheel": wheel_record,
        "status": "pass" if extensions and not any(item["missing_dependency"] for item in extension_records) else "fail",
    }


def write_installation_report(report: dict, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
