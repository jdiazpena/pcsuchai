import hashlib
import json
from pathlib import Path

import pytest
import pcsuchai.preflight as preflight
from pcsuchai.preflight import _pinned_versions, run_preflight


def test_exact_version_policy_parser(tmp_path: Path) -> None:
    policy = tmp_path / "requirements.txt"
    policy.write_text("# comment\nnumpy==1.2.3\npsutil==7.0.0 # reason\n")
    assert _pinned_versions(policy) == {"numpy": "1.2.3", "psutil": "7.0.0"}


def test_preflight_detects_input_digest_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("trusted")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {"input.txt": hashlib.sha256(b"other").hexdigest()}}))
    result = run_preflight(
        tmp_path, tmp_path / "out", orbit_backends=(), magnetic_backends=(),
        input_manifest=manifest, minimum_free_bytes=0,
    )
    assert result["status"] == "fail"
    assert "input:input.txt" in result["failed_checks"]


@pytest.mark.parametrize("backend,expected_modules", [
    ("astropy", ["astropy.units", "astropy.coordinates", "astropy.time", "astropy.utils.iers", "sgp4.api"]),
    ("skyfield", ["skyfield.api", "sgp4.api"]),
])
def test_orbit_preflight_loads_runtime_modules(monkeypatch, backend, expected_modules) -> None:
    """Lazy top-level package imports must not substitute for runtime checks."""

    imports = []
    monkeypatch.setattr(preflight.importlib, "import_module", lambda name: imports.append(name))
    assert preflight._backend_smoke(backend) == "imports succeeded"
    assert imports == expected_modules


def test_preflight_rejects_astropy_numpy_runtime_incompatibility(monkeypatch, tmp_path: Path) -> None:
    """Report the missing-in1d failure before starting any measured child run."""

    def import_module(name):
        if name == "astropy.units":
            raise AttributeError("module 'numpy' has no attribute 'in1d'")
        return None

    monkeypatch.setattr(preflight.importlib, "import_module", import_module)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": {}}))
    result = run_preflight(
        tmp_path, tmp_path / "out", orbit_backends=("astropy",), magnetic_backends=(),
        input_manifest=manifest, minimum_free_bytes=0,
    )
    assert result["status"] == "fail"
    assert "backend:astropy" in result["failed_checks"]
    check = next(item for item in result["checks"] if item["name"] == "backend:astropy")
    assert "AttributeError" in check["detail"]
    assert "in1d" in check["detail"]
