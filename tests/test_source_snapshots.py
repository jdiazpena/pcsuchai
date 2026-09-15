import hashlib
import tarfile

import pytest

from pcsuchai.retention import snapshot_sources
from pcsuchai.benchmark_suite import _source_digest


def source_record(contents):
    return {"files": [{"path": "source.py", "sha256": hashlib.sha256(contents).hexdigest(),
                       "size_bytes": len(contents)}]}


def test_source_snapshot_validates_archived_bytes(tmp_path):
    contents = b"original source\n"
    (tmp_path / "source.py").write_bytes(contents)
    result = snapshot_sources(tmp_path, source_record(contents), tmp_path / "source.tar.gz")
    assert result["sha256"]
    with tarfile.open(result["path"]) as archive:
        assert archive.extractfile("source.py").read() == contents


def test_source_change_during_tar_read_is_not_certified(tmp_path, monkeypatch):
    contents = b"original source\n"
    source = tmp_path / "source.py"
    source.write_bytes(contents)
    original = tarfile.TarFile.add

    def mutate_during_add(archive, name, *args, **kwargs):
        source.write_bytes(b"modified source\n")
        return original(archive, name, *args, **kwargs)

    monkeypatch.setattr(tarfile.TarFile, "add", mutate_during_add)
    destination = tmp_path / "partial.tar.gz"
    with pytest.raises(RuntimeError, match="bytes changed"):
        snapshot_sources(tmp_path, source_record(contents), destination)
    assert destination.is_file()  # preserve failed reproducibility evidence


def test_source_identity_ignores_generated_distribution_metadata(tmp_path):
    """Installing/building the same source cannot alter its scientific identity."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1"\n')
    source = tmp_path / "src/fixture/model.py"
    source.parent.mkdir(parents=True)
    source.write_text("model_version = 1\n")
    requirements = tmp_path / "requirements/common.txt"
    requirements.parent.mkdir()
    requirements.write_text("numpy==2.5.2\n")
    before = _source_digest(tmp_path)
    for name in ("fixture.egg-info", "fixture-1.dist-info"):
        generated = tmp_path / "src" / name / "SOURCES.txt"
        generated.parent.mkdir()
        generated.write_text("build-dependent file listing\n")
    assert _source_digest(tmp_path) == before
    source.write_text("model_version = 2\n")
    changed_source = _source_digest(tmp_path)
    assert changed_source["sha256"] != before["sha256"]
    requirements.write_text("numpy==2.4.0\n")
    assert _source_digest(tmp_path)["sha256"] != changed_source["sha256"]
