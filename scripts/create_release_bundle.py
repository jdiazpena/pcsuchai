#!/usr/bin/env python3
"""Package a clean committed public tree and opaque metadata-checked Apex wheels."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import tomllib
from uuid import uuid4
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _git_command(root: Path, *arguments: str) -> list[str]:
    """Use the workspace's alternate metadata or an ordinary operator checkout."""

    alternate = root / ".pcsuchai-git"
    prefix = ["git", "-C", str(root)]
    if (alternate / "HEAD").is_file():
        prefix.append(f"--git-dir={alternate}")
    return [*prefix, *arguments]


def _git(root: Path, *arguments: str) -> bytes:
    """Acquire committed Git metadata without changing refs/index/source files."""

    return subprocess.run(_git_command(root, *arguments), check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def _public_path(name: str) -> bool:
    """Exclude private/generated material even if accidentally committed."""

    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    if name == "release-manifest.json":
        # This name is reserved for this bundle's newly generated inventory.
        # A committed file must not create duplicate, ambiguous TAR members.
        return False
    if any(part in (".git", ".pcsuchai-git", ".agents", ".codex", "__pycache__",
                    ".venv", "venv", ".pytest_cache") for part in path.parts):
        return False
    if path.parts[0] in ("archive", "installation-reports", "operation-costs", "dist", "build"):
        return False
    if path.parts[0] == "outputs":
        return name == "outputs/.gitkeep"
    if name.startswith("vendor/sources/") or name.startswith("vendor/wheels/"):
        return False
    if name.startswith("data/raw/"):
        return name in ("data/raw/README.md", "data/raw/langmuir-2018-2.csv")
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return False
    return True


def _cached_wheels(root: Path) -> list[tuple[str, bytes]]:
    """Capture regular Apex 2.1.1 wheels with matching filename/directory/WHEEL tags.

    This checks opaque distribution metadata, not ARM execution or scientific
    accuracy. Operators still run dependency/native/full-data acceptance.
    """

    cache = root / "vendor/wheels"
    if not cache.exists() and not cache.is_symlink():
        return []
    if cache.is_symlink():
        raise ValueError("native cache cannot be a symlink")
    result = []
    for path in sorted(cache.rglob("*.whl")):
        relative = path.relative_to(cache)
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
            raise ValueError(f"unsafe linked native wheel: {relative}")
        match = re.fullmatch(r"apexpy-2\.1\.1-(cp\d+)-\1-(linux_[a-zA-Z0-9_]+)\.whl", path.name)
        if not match or len(relative.parts) != 2:
            raise ValueError(f"unsupported cached wheel name/layout: {relative}")
        python_tag, platform_tag = match.groups()
        if relative.parts[0] != f"{platform_tag.removeprefix('linux_')}-{python_tag}":
            raise ValueError(f"cached architecture/Python tags disagree: {relative}")
        data = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            metadata = archive.read("apexpy-2.1.1.dist-info/METADATA").decode("utf-8")
            wheel = archive.read("apexpy-2.1.1.dist-info/WHEEL").decode("utf-8")
        if ("Name: apexpy" not in metadata.splitlines() or "Version: 2.1.1" not in metadata.splitlines()
                or f"Tag: {python_tag}-{python_tag}-{platform_tag}" not in wheel.splitlines()):
            raise ValueError(f"cached wheel metadata does not match its tags: {relative}")
        result.append((path.relative_to(root).as_posix(), data))
    return result


def _append_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add captured bytes with fixed ordinary-file metadata, without extraction."""

    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def build_bundle(root: Path, destination: Path) -> dict:
    """Publish source/checksum exclusively; keep recoverable partials on failure."""

    root, destination = root.resolve(), destination.resolve()
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("invalid committed source identity")
    clean = subprocess.run(_git_command(root, "diff", "--quiet", "HEAD", "--"))
    if clean.returncode:
        raise ValueError("commit tracked source changes before creating a release bundle")
    paths = _git(root, "ls-tree", "-r", "--name-only", "-z", commit).decode().split("\0")
    paths = [name for name in paths if name]
    forbidden = [name for name in paths if not _public_path(name)]
    if forbidden:
        raise ValueError(f"committed private/generated release paths are forbidden: {forbidden}")
    project = tomllib.loads(_git(root, "show", f"{commit}:pyproject.toml").decode())
    version = project["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*", version):
        raise ValueError("unsafe project version")
    wheels = _cached_wheels(root)
    prefix = f"pcsuchai-{version}"
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{prefix}-{commit[:12]}.tar.gz"
    checksum = output.with_name(output.name + ".sha256")
    if any(path.exists() or path.is_symlink() for path in (output, checksum)):
        raise FileExistsError(f"release archive/checksum already exists: {output}")
    descriptor, source_name = tempfile.mkstemp(prefix=".pcsuchai-source-", suffix=".tar", dir=destination)
    source_path = Path(source_name)
    with os.fdopen(descriptor, "wb") as source:
        subprocess.run(_git_command(root, "archive", "--format=tar", commit), stdout=source,
                       stderr=subprocess.PIPE, check=True)
        source.flush()
        os.fsync(source.fileno())
    temporary = output.with_name(f".{output.name}.{uuid4().hex}.partial")
    inventory = []
    source_members = set()
    with temporary.open("xb") as compressed:
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as stream:
            with tarfile.open(fileobj=stream, mode="w|") as bundle, tarfile.open(source_path) as exported:
                for info in exported:
                    name = info.name.rstrip("/")
                    if info.isdir():
                        continue
                    if not info.isfile() or not _public_path(name):
                        raise ValueError(f"unsafe committed archive member: {name}")
                    data = exported.extractfile(info).read()
                    source_members.add(name)
                    inventory.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                    info.name = f"{prefix}/{name}"
                    bundle.addfile(info, io.BytesIO(data))
                if source_members != set(paths):
                    raise ValueError("Git archive omitted or added committed release files")
                for name, data in wheels:
                    _append_bytes(bundle, f"{prefix}/{name}", data)
                    inventory.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                manifest = {"schema_version": 1, "git_commit": commit, "version": version,
                            "files": inventory, "wheel_validation": "opaque metadata/tag agreement, not native runtime or scientific acceptance"}
                _append_bytes(bundle, f"{prefix}/release-manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        compressed.flush()
        os.fsync(compressed.fileno())
    with tarfile.open(temporary) as archive:
        acquired = {info.name.removeprefix(prefix + "/"): hashlib.sha256(archive.extractfile(info).read()).hexdigest()
                    for info in archive if info.isfile()}
    if any(acquired.get(row["path"]) != row["sha256"] for row in inventory) or len(acquired) != len(inventory) + 1:
        raise ValueError("release bundle retained-byte verification failed")
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    # Exclusive hard-link commits cannot replace a competing publication. On a
    # filesystem without hard links the partial remains; use a Linux destination.
    os.link(temporary, output)
    with checksum.open("x", encoding="utf-8") as stream:
        stream.write(f"{digest}  {output.name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.unlink()  # only the exact newly-created, verified temporary names
    source_path.unlink()
    return {"bundle": str(output), "checksum": str(checksum), "sha256": digest,
            "git_commit": commit, "version": version, "files": len(inventory), "cached_apex_wheels": len(wheels)}


def main() -> int:
    """Build the maintainer's committed release without importing scientific code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    print(json.dumps(build_bundle(ROOT, arguments.destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
