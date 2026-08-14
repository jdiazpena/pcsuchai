import hashlib
import json
from pathlib import Path

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
