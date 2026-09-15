"""Read-only provenance for actual software, native libraries and board policy.

Installed extension hashes are not wheel-archive hashes. Compiler discovery is
not evidence that that compiler built a downloaded wheel. Unknown build/cooling
details remain explicitly unknown. Nothing here changes the operating system,
frequency policy, caches, sensors or numerical-library thread settings.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")


def native_thread_state() -> dict:
    """Inspect loaded BLAS/OpenMP thread limits, separately from environment.

    The counts are configured native pool limits, not a claim that every thread
    is simultaneously busy. An empty list is not an invented one-thread result.
    This inexpensive snapshot does not hash libraries or import scientific
    backends and can be recorded after each complete worker job.
    """

    result = {"captured_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "calling_process_loaded_native_libraries",
              "source": "threadpoolctl.threadpool_info",
              "environment": {key: os.environ.get(key) for key in THREAD_VARIABLES}}
    try:
        from threadpoolctl import threadpool_info
        pools = threadpool_info()
        result.update(status="available", libraries=pools,
                      one_thread_verified=bool(pools) and all(pool.get("num_threads") == 1 for pool in pools),
                      reason=None if pools else "no recognized loaded thread-pool library")
    except (ImportError, OSError, RuntimeError) as exc:
        result.update(status="unavailable", libraries=[], one_thread_verified=False,
                      reason=f"{type(exc).__name__}: {exc}")
    return result


def _read(path: str | Path) -> dict:
    """Preserve availability/source for a read-only kernel or OS text field."""

    path = Path(path)
    try:
        return {"status": "available", "source": str(path), "value": path.read_text().strip()}
    except (OSError, UnicodeError) as exc:
        return {"status": "unavailable", "source": str(path), "value": None,
                "reason": f"{type(exc).__name__}: {exc}"}


def _command(command: list[str]) -> dict:
    """Discover a tool/version with a bounded direct command, never a shell."""

    if shutil.which(command[0]) is None:
        return {"status": "unavailable", "source": command, "value": None, "reason": "tool not installed"}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        return {"status": "available" if result.returncode == 0 else "unavailable", "source": command,
                "value": result.stdout.strip(), "stderr": result.stderr.strip(), "return_code": result.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "source": command, "value": None,
                "reason": f"{type(exc).__name__}: {exc}"}


def _installation_artifacts(root: Path) -> dict:
    """Index pip artifact digests without exposing repository URLs/credentials.

    A pip report of a source archive proves that archive's digest, not a locally
    built wheel's digest. Cached wheel files provide actual wheel-byte hashes.
    Earlier reports with another version cannot describe the installed version.
    """

    from .benchmark import sha256_file
    from packaging.utils import canonicalize_name, parse_wheel_filename
    from packaging.tags import sys_tags

    found = {}
    compatible_tags = set(sys_tags())
    reports = list((root / "installation-reports").glob("*/pip-*.json"))
    reports += list((root / "outputs/verification/initial-implementation").glob("*install.json"))
    for report in sorted(reports):
        try:
            data = json.loads(report.read_text())
            for item in data.get("install", []):
                info = item.get("download_info", {})
                name, version = item["metadata"]["name"], item["metadata"]["version"]
                filename = Path(urlsplit(info.get("url", "")).path).name
                if filename.endswith(".whl") and not (parse_wheel_filename(filename)[3] & compatible_tags):
                    continue
                digest = info.get("archive_info", {}).get("hashes", {}).get("sha256")
                if digest:
                    found.setdefault((canonicalize_name(name), version), []).append({
                        "filename": filename, "sha256": digest,
                        "kind": "wheel_archive" if filename.endswith(".whl") else "source_or_other_archive",
                        "evidence_source": report.relative_to(root).as_posix()})
        except (OSError, ValueError, KeyError, TypeError):
            # Old unrelated malformed reports cannot manufacture provenance.
            continue
    for wheel in sorted((root / "vendor/wheels").glob("*/*.whl")):
        try:
            name, version, _build, tags = parse_wheel_filename(wheel.name)
            if not tags & compatible_tags:
                continue
            found.setdefault((canonicalize_name(name), str(version)), []).append({
                "filename": wheel.name, "sha256": sha256_file(wheel), "kind": "wheel_archive",
                "evidence_source": wheel.relative_to(root).as_posix()})
        except (OSError, ValueError):
            continue
    return found


def dependency_provenance(requirements: list[str], project_root: str | Path) -> dict:
    """Record the active transitive closure, every dependency edge and native hash.

    Root requirements select extras/platform markers. Unrelated installed typing
    or application packages are deliberately excluded. The running checkout's
    project manifest is authoritative for its own requirements; distribution
    absence is recorded rather than disguised as an installed project wheel.
    """

    from .benchmark import sha256_file
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name

    root = Path(project_root).resolve()
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    artifacts = _installation_artifacts(root)
    environment = default_environment()
    pending, visited, packages, edges, errors = deque((Requirement(item), "experiment") for item in requirements), set(), {}, [], []
    while pending:
        requirement, parent = pending.popleft()
        if requirement.marker and not requirement.marker.evaluate({**environment, "extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        key = (name, tuple(sorted(requirement.extras)))
        installed = None
        try:
            installed = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            if name != canonicalize_name(project["name"]):
                edges.append({"parent": parent, "requirement": str(requirement), "status": "missing"})
                errors.append(f"{parent} requires {requirement}: package not installed")
                continue
        checkout = name == canonicalize_name(project["name"])
        version = project["version"] if checkout else installed.version
        compatible = requirement.specifier.contains(version, prereleases=True)
        edges.append({"parent": parent, "requirement": str(requirement), "installed_version": version,
                      "status": "satisfied" if compatible else "version_mismatch"})
        if not compatible:
            errors.append(f"{parent} requires {requirement}: version is {version}")
        if key in visited:
            continue
        visited.add(key)
        if checkout:
            lines = list(project.get("dependencies", []))
            for extra in requirement.extras:
                if extra not in project.get("optional-dependencies", {}):
                    errors.append(f"unknown project extra: {extra}")
                lines += project.get("optional-dependencies", {}).get(extra, [])
            python_spec = project.get("requires-python")
            record = {"name": name, "version": version, "metadata_source": "running_checkout_pyproject",
                      "location": str(root), "distribution_installed": installed is not None,
                      "native_extensions": [], "wheel_metadata": None,
                      "project_manifest_sha256": sha256_file(root / "pyproject.toml")}
        else:
            lines = list(installed.requires or [])
            python_spec = installed.metadata.get("Requires-Python")
            native = []
            for file in installed.files or []:
                if str(file).endswith((".so", ".pyd", ".dylib")):
                    path = Path(installed.locate_file(file)).resolve()
                    native.append({"path": str(path), "size_bytes": path.stat().st_size,
                                   "sha256": sha256_file(path), "kind": "installed_native_file_not_wheel_archive"})
            wheel = installed.read_text("WHEEL")
            record = {"name": name, "version": version, "location": str(Path(installed.locate_file("")).resolve()),
                      "metadata_source": "installed_distribution", "distribution_installed": True,
                      "requires_python": python_spec, "native_extensions": native,
                      "wheel_metadata": wheel, "installer": installed.read_text("INSTALLER")}
        record["installation_artifacts"] = artifacts.get((name, version), [])
        record["artifact_binding"] = "retained reports/caches with matching version and compatible wheel tags; installed file digests recorded separately"
        record["wheel_hash_status"] = "available" if any(item["kind"] == "wheel_archive" for item in record["installation_artifacts"]) else "unavailable"
        record["wheel_hash_reason"] = None if record["wheel_hash_status"] == "available" else "no matching retained wheel/archive report; installed hashes cannot reconstruct its original wheel"
        packages[name] = record
        if python_spec and not SpecifierSet(python_spec).contains(environment["python_full_version"], prereleases=True):
            errors.append(f"{name} requires Python {python_spec}")
        for line in lines:
            child = Requirement(line)
            if child.marker and not any(child.marker.evaluate({**environment, "extra": extra}) for extra in {"", *requirement.extras}):
                continue
            child.marker = None  # the parent's extras have already been tested
            pending.append((child, name))
    return {"status": "pass" if not errors else "fail", "scope": "declared_active_runtime_dependency_closure",
            "requirements": requirements, "packages": [packages[name] for name in sorted(packages)],
            "edges": edges, "errors": errors}


def experiment_provenance(project_root: str | Path, pairs: list[str], storage_path: str | Path,
                          system_notes: dict | None = None, *, full_validation: bool = False) -> dict:
    """Capture static setup/build/board evidence outside measured attempt clocks."""

    from .benchmark import runtime_metadata, sha256_file

    root, storage = Path(project_root).resolve(), Path(storage_path).resolve()
    selected = {"benchmark"}
    for pair in pairs:
        orbit, magnetic = pair.split("-")
        selected.add(f"orbit-{orbit}")
        selected.add("magnetic-apex" if magnetic == "apexpy" else "magnetic-aacgm")
    if full_validation:
        selected.update(("orbit-astropy", "orbit-skyfield", "magnetic-apex", "magnetic-aacgm"))
    closure = dependency_provenance([f"pcsuchai[{','.join(sorted(selected))}]"], root)
    threads = native_thread_state()
    for pool in threads["libraries"]:
        library = Path(pool["filepath"])
        pool["installed_library_sha256"] = sha256_file(library) if library.is_file() else None
    numpy_build = None
    if "numpy" in sys.modules:
        numpy_build = getattr(sys.modules["numpy"].__config__, "CONFIG", None)
    stat = os.statvfs(storage)
    filesystem = {"path": str(storage), "available_bytes": stat.f_bavail * stat.f_frsize,
                  "available_inodes": stat.f_favail, "block_size_bytes": stat.f_frsize,
                  "source": "os.statvfs", "unit": "bytes/inodes"}
    zram = []
    for device in sorted(Path("/sys/block").glob("zram*")):
        zram.append({"device": device.name, **{name: _read(device / name) for name in ("disksize", "mm_stat", "comp_algorithm")}})
    notes = system_notes or {}
    config = {key: {"status": "operator_reported" if notes.get(key) else "unknown", "value": notes.get(key),
                    "source": "frozen_manifest.system_notes" if notes.get(key) else "not supplied"}
              for key in ("cooling", "storage", "supply", "other")}
    return {"schema_version": 1, "captured_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "experiment_setup_not_measured_job", "runtime": runtime_metadata(),
            "python_abi": {key: sysconfig.get_config_var(key) for key in ("SOABI", "EXT_SUFFIX", "CC", "CFLAGS", "CONFIG_ARGS")},
            "dependency_closure": closure, "native_threads": threads, "numpy_wheel_build_configuration": numpy_build,
            "current_build_tool_discovery_not_wheel_compiler": {name: _command([name, "--version"]) for name in ("gcc", "gfortran", "meson", "ninja")},
            "firmware_version": _command(["vcgencmd", "version"]),
            "firmware_integer_configuration": _command(["vcgencmd", "get_config", "int"]),
            "os_release": _read("/etc/os-release"), "kernel_release": platform.release(),
            "effective_affinity": sorted(os.sched_getaffinity(0)),
            "cpu_governors": [_read(path) for path in sorted(Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"))],
            "swaps": _read("/proc/swaps"), "zram": zram,
            "filesystem": filesystem, "known_configuration": config,
            "apex_build_fix": {"recipe": "packaging/apexpy-2.1.1-optional-quadmath.patch",
                               "recipe_sha256": sha256_file(root / "packaging/apexpy-2.1.1-optional-quadmath.patch"),
                               "application_status": "consult retained installation/build evidence; recipe presence alone does not prove application"}}
