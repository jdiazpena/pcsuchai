"""Handle source checkouts where the canonical measurement input is missing."""

from pathlib import Path

import pytest


DATA_REQUIRED_MODULES = {
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
        reason="canonical data/raw/langmuir-2018-2.csv is not present"
    )
    for item in items:
        if Path(str(item.fspath)).name in DATA_REQUIRED_MODULES:
            item.add_marker(marker)
