#!/usr/bin/env python3
"""Check only SUCHAI's pinned packages and their runtime dependency closure."""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name


def check_dependencies(requirements: list[str]) -> dict:
    """Check pins, Python compatibility and recursively required package versions.

    Only packages reachable from the supplied runtime requirements are read.
    Platform markers and explicitly requested extras are respected; unrelated
    installed packages and unrequested development extras are not inspected.
    Each dependency edge is version-checked, even if its package was visited
    earlier through another parent. Cycles are traversed only once per extras
    selection. This function is read-only and installs or repairs nothing.
    """

    pending = deque((Requirement(line), "SUCHAI version policy") for line in requirements)
    environment = default_environment()
    visited: set[tuple[str, tuple[str, ...]]] = set()
    packages: dict[str, dict] = {}
    errors: list[str] = [] if requirements else ["The SUCHAI version policy is empty."]

    while pending:
        requirement, parent = pending.popleft()
        if requirement.marker and not requirement.marker.evaluate({**environment, "extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        try:
            installed = distribution(name)
        except PackageNotFoundError:
            errors.append(f"{parent} requires {requirement}: package is not installed")
            continue
        if not requirement.specifier.contains(installed.version, prereleases=True):
            errors.append(f"{parent} requires {requirement}: installed version is {installed.version}")

        packages[name] = {
            "name": name, "version": installed.version,
            "location": str(Path(installed.locate_file("")).resolve()),
        }
        key = (name, tuple(sorted(requirement.extras)))
        if key in visited:
            continue
        visited.add(key)
        python_requirement = installed.metadata.get("Requires-Python")
        if python_requirement and not SpecifierSet(python_requirement).contains(
            environment["python_full_version"], prereleases=True
        ):
            errors.append(f"{name} requires Python {python_requirement}: running {environment['python_full_version']}")

        for line in installed.requires or ():
            dependency = Requirement(line)
            if dependency.marker and not any(
                dependency.marker.evaluate({**environment, "extra": extra})
                for extra in {"", *requirement.extras}
            ):
                continue
            # The parent's extras marker was already evaluated. It must not be
            # evaluated again against the child package's extras selection.
            dependency.marker = None
            pending.append((dependency, name))

    return {
        "schema_version": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        "scope": "SUCHAI pinned packages and their active runtime dependencies",
        "requirements": requirements,
        "status": "fail" if errors else "pass",
        "packages": [packages[name] for name in sorted(packages)],
        "errors": errors,
    }


def main() -> int:
    """Write dependency evidence and return nonzero only for SUCHAI failures."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    requirements = [
        text for line in arguments.policy.read_text().splitlines()
        if (text := line.split("#", 1)[0].strip())
    ]
    result = check_dependencies(requirements)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for package in result["packages"]:
        print(f"Dependency checked: {package['name']}=={package['version']} at {package['location']}")
    for error in result["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    print(f"SUCHAI dependencies {result['status'].upper()}: {arguments.report}")
    return 0 if result["status"] == "pass" else 5


if __name__ == "__main__":
    raise SystemExit(main())
