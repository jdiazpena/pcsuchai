"""Public committed-source packaging and immutable publication safety tests."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "release_bundle", Path(__file__).resolve().parents[1] / "scripts/create_release_bundle.py")
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


def git(root, *args):
    """Run Git only in the explicitly test-owned temporary repository."""
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path):
    """Create an isolated committed public fixture, without external state."""
    root = tmp_path / "repository"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname="pcsuchai"\nversion="0.1.0"\n')
    (root / "README.md").write_text("public source\n")
    (root / "data/raw").mkdir(parents=True)
    (root / "data/raw/langmuir-2018-2.csv").write_bytes(b"trusted canonical bytes\n")
    git(root, "init")
    git(root, "config", "user.name", "Bundle test")
    git(root, "config", "user.email", "bundle-test@example.invalid")
    git(root, "add", "pyproject.toml", "README.md", "data/raw/langmuir-2018-2.csv")
    git(root, "commit", "-m", "public fixture")
    return root


def wheel(root, *, directory="aarch64-cp313", version="2.1.1"):
    """Create opaque synthetic wheel metadata; never claim a real ARM binary."""
    path = root / "vendor/wheels" / directory / "apexpy-2.1.1-cp313-cp313-linux_aarch64.whl"
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("apexpy-2.1.1.dist-info/METADATA", f"Name: apexpy\nVersion: {version}\n")
        archive.writestr("apexpy-2.1.1.dist-info/WHEEL", "Tag: cp313-cp313-linux_aarch64\n")
    return path


def test_only_committed_public_files_and_metadata_checked_wheels_are_packaged(repository, tmp_path):
    """Untracked secrets/reports/raw alternatives never enter the published tree."""
    for name in ("archive/private.csv", "installation-reports/install.log", ".env",
                 "data/raw/private.xlsx", "scientific_comparison.py"):
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"untracked private material\n")
    cached = wheel(repository)
    result = bundle.build_bundle(repository, tmp_path / "releases")
    assert result["cached_apex_wheels"] == 1
    with tarfile.open(result["bundle"]) as archive:
        names = archive.getnames()
        assert not any("private" in name or "installation-reports" in name or name.endswith(".env")
                       or "scientific_comparison.py" in name for name in names)
        assert archive.extractfile("pcsuchai-0.1.0/data/raw/langmuir-2018-2.csv").read() == b"trusted canonical bytes\n"
        assert archive.extractfile("pcsuchai-0.1.0/" + cached.relative_to(repository).as_posix()).read() == cached.read_bytes()
        manifest = json.load(archive.extractfile("pcsuchai-0.1.0/release-manifest.json"))
    assert manifest["git_commit"] == result["git_commit"] and len(manifest["files"]) == 4
    assert "not native runtime" in manifest["wheel_validation"]


def test_second_publication_cannot_replace_archive_or_checksum(repository, tmp_path):
    """Repeated invocation preserves both original release artifacts exactly."""
    result = bundle.build_bundle(repository, tmp_path / "releases")
    archive, checksum = Path(result["bundle"]), Path(result["checksum"])
    before = archive.read_bytes(), checksum.read_bytes()
    with pytest.raises(FileExistsError):
        bundle.build_bundle(repository, tmp_path / "releases")
    assert (archive.read_bytes(), checksum.read_bytes()) == before


def test_dirty_committed_source_is_refused(repository, tmp_path):
    """A release cannot silently omit the maintainer's uncommitted code edits."""
    (repository / "README.md").write_text("uncommitted changed source\n")
    with pytest.raises(ValueError, match="commit tracked source"):
        bundle.build_bundle(repository, tmp_path / "releases")


@pytest.mark.parametrize("name", ["archive/private.csv", "data/raw/private.xlsx", ".env", "installation-reports/install.log", "release-manifest.json"])
def test_accidentally_committed_private_material_is_refused(repository, tmp_path, name):
    """Even tracked private/generated data cannot be republished by the helper."""
    path = repository / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private fixture\n")
    git(repository, "add", name)
    git(repository, "commit", "-m", "intentionally forbidden test fixture")
    with pytest.raises(ValueError, match="private/generated"):
        bundle.build_bundle(repository, tmp_path / "releases")


@pytest.mark.parametrize("directory,version", [("armv6l-cp313", "2.1.1"), ("aarch64-cp313", "9.9.9")])
def test_cached_wheel_tag_or_version_mismatch_is_refused(repository, tmp_path, directory, version):
    """Synthetic mismatched distribution metadata cannot masquerade as a cache."""
    wheel(repository, directory=directory, version=version)
    with pytest.raises(ValueError, match="disagree|metadata"):
        bundle.build_bundle(repository, tmp_path / "releases")


def test_linked_cache_is_refused_without_reading_outside_bytes(repository, tmp_path):
    """A wheel-cache symlink cannot import unrelated local files into a release."""
    outside = tmp_path / "private-wheel-directory"
    outside.mkdir()
    (repository / "vendor").mkdir()
    (repository / "vendor/wheels").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        bundle.build_bundle(repository, tmp_path / "releases")
