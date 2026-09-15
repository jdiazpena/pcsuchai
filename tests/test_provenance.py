import json
import os
from pathlib import Path

import numpy as np

from pcsuchai.experiment_control import numerical_controls
from pcsuchai.provenance import dependency_provenance, experiment_provenance, native_thread_state


ROOT = Path(__file__).resolve().parents[1]


def test_one_thread_policy_applies_to_existing_pools_and_restores_stock():
    before = native_thread_state()
    assert before["status"] == "available" and before["libraries"]
    original = dict(os.environ)
    with numerical_controls("one", None):
        current = native_thread_state()
        assert current["one_thread_verified"]
        assert all(pool["num_threads"] == 1 for pool in current["libraries"])
    assert native_thread_state()["libraries"] == before["libraries"]
    assert os.environ == original


def test_closure_records_transitive_edges_native_hashes_and_excludes_unrelated():
    result = dependency_provenance(["pcsuchai[orbit-skyfield,benchmark]"], ROOT)
    assert result["status"] == "pass", result["errors"]
    packages = {record["name"]: record for record in result["packages"]}
    assert {"numpy", "matplotlib", "skyfield", "sgp4", "jplephem", "threadpoolctl", "psutil"} <= packages.keys()
    assert not {"apexpy", "aacgmv2", "pytest", "types-seaborn"} & packages.keys()
    assert packages["numpy"]["native_extensions"]
    assert all(len(item["sha256"]) == 64 for item in packages["numpy"]["native_extensions"])
    assert packages["pcsuchai"]["metadata_source"] == "running_checkout_pyproject"
    assert any(edge["parent"] == "skyfield" and edge["requirement"].startswith("jplephem") for edge in result["edges"])
    # A vendored ARM/cp313 Apex wheel cannot describe local x86/cp314 binaries.
    apex = dependency_provenance(["apexpy==2.1.1"], ROOT)
    package = next(record for record in apex["packages"] if record["name"] == "apexpy")
    assert not any("aarch64" in artifact["filename"] for artifact in package["installation_artifacts"])


def test_dependency_mismatch_is_failure_not_repair():
    result = dependency_provenance(["numpy==0.0.1"], ROOT)
    assert result["status"] == "fail"
    assert any("version" in error for error in result["errors"])
    assert np.__version__ == "2.5.2"


def test_setup_provenance_preserves_unknown_configuration_and_actual_build_roles(tmp_path):
    result = experiment_provenance(ROOT, ["skyfield-apexpy"], tmp_path, {"cooling": "operator's existing setup"})
    assert result["dependency_closure"]["status"] == "pass"
    assert result["known_configuration"]["cooling"]["status"] == "operator_reported"
    assert result["known_configuration"]["storage"]["status"] == "unknown"
    assert result["python_abi"]["SOABI"]
    assert result["numpy_wheel_build_configuration"]["Build Dependencies"]["blas"]["found"]
    assert result["native_threads"]["libraries"][0]["installed_library_sha256"]
    assert "not_wheel_compiler" in next(key for key in result if key.startswith("current_build_tool"))
    json.dumps(result)  # all retained metadata must be serializable
