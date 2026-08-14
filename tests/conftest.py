"""Test-suite handling for the private canonical measurement dataset."""

from pathlib import Path

import pytest


PRIVATE_DATA_MODULES = {
    "test_data.py",
    "test_full_validation.py",
    "test_orbit_backends.py",
    "test_orbit_benchmark.py",
    "test_orbit_integrity.py",
    "test_pipeline.py",
    "test_tle.py",
    "test_validation.py",
}


def pytest_collection_modifyitems(config, items) -> None:
    """Skip only integration tests requiring telemetry when it is unavailable."""

    root = Path(str(config.rootpath))
    if (root / "data/raw/langmuir-2018-2.csv").is_file():
        return
    marker = pytest.mark.skip(
        reason="private data/raw/langmuir-2018-2.csv is not present"
    )
    for item in items:
        if Path(str(item.fspath)).name in PRIVATE_DATA_MODULES:
            item.add_marker(marker)
