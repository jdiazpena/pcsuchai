"""Lossless experiment transfer with immutable originals and safe path rebasing.

An exported bundle contains every experiment file, including failed/partial
attempts, raw samples and snapshots. SHA-256 covers the original bytes. Paths
inside the original JSON records are not rewritten; a resolver maps their
recorded root to the imported root. Export is byte-integrity verification, not
a scientific certificate or permission to resume on another board.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

from .run_lock import serialized_run
from .operation_costs import measured_operation


INDEX = ".pcsuchai-bundle-index.jsonl"
METADATA = ".pcsuchai-bundle-metadata.json"


def _relative(value: str) -> PurePosixPath:
    """Reject traversal, absolute, ambiguous and Windows-style member paths."""

    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("invalid portable relative path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or ".." in path.parts or ":" in path.parts[0] or str(path) != value:
        raise ValueError(f"unsafe portable path: {value}")
    return path


def _entries(root: Path):
    """Walk files/directories in stable order, preserving empty partial attempts."""

    for parent, directories, names in os.walk(root, followlinks=False):
        directories.sort()
        if Path(parent) != root:
            yield Path(parent)
        for name in directories:
            if (Path(parent) / name).is_symlink():
                raise ValueError(f"experiment contains a directory symlink: {Path(parent) / name}")
        for name in sorted(names):
            path = Path(parent) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"experiment contains a non-regular file: {path}")
            yield path


def _tar_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    """Add one deterministic envelope document, not a mutable source record."""

    member = tarfile.TarInfo(name)
    member.size, member.mode, member.mtime = len(data), 0o644, 0
    archive.addfile(member, io.BytesIO(data))


@serialized_run
@measured_operation("export", "output", input_argument="directory")
def export_experiment(directory: str | Path, output: str | Path) -> dict:
    """Export an inactive experiment, never overwriting or deleting an archive.

    The device lock excludes concurrent benchmark I/O. A live experiment must
    be stopped first. A same-directory temporary archive is fsynced and checked
    before an exclusive hard-link commit. Failed export leaves its temporary
    archive available for diagnosis; no retained experiment bytes are removed.
    """

    from .benchmark import sha256_file
    from .experiment_control import experiment_status

    started = time.monotonic()
    root, destination = Path(directory).resolve(), Path(output).resolve()
    if destination.is_relative_to(root):
        raise ValueError("bundle destination must be outside its experiment")
    status = experiment_status(root)
    if status["live"]:
        raise ValueError("stop the verified live experiment before export")
    if destination.exists():
        raise FileExistsError(destination)
    # Imported bundles can be exported again after checking their existing
    # envelope; the regenerated index describes the same original payload.
    if (root / METADATA).exists() or (root / INDEX).exists():
        verify_import(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent)
    temporary = Path(temporary_name)
    files, directories, logical_bytes, physical_bytes = 0, 0, 0, 0
    inodes = {}
    index_digest = hashlib.sha256()
    with os.fdopen(descriptor, "wb") as output_handle, tempfile.TemporaryFile("w+b") as index:
        with gzip.GzipFile(filename="", fileobj=output_handle, mode="wb", mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for path in _entries(root):
                    relative = path.relative_to(root).as_posix()
                    if relative in (INDEX, METADATA):
                        continue
                    _relative(relative)
                    initial = path.stat()
                    member = archive.gettarinfo(str(path), arcname=f"payload/{relative}")
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    member.mtime = 0
                    if path.is_dir():
                        archive.addfile(member)
                        line = (json.dumps({"path": relative, "kind": "directory"}, sort_keys=True,
                                           separators=(",", ":")) + "\n").encode()
                        index.write(line)
                        index_digest.update(line)
                        directories += 1
                        continue
                    digest = sha256_file(path)
                    # Preserve sharing within the bundle, not links outside it.
                    identity = (initial.st_dev, initial.st_ino)
                    if identity in inodes:
                        member.type, member.linkname, member.size = tarfile.LNKTYPE, inodes[identity], 0
                        archive.addfile(member)
                    else:
                        member.type, member.linkname, member.size = tarfile.REGTYPE, "", initial.st_size
                        with path.open("rb") as source:
                            archive.addfile(member, source)
                        inodes[identity] = member.name
                        physical_bytes += getattr(initial, "st_blocks", 0) * 512
                    if sha256_file(path) != digest or path.stat().st_size != initial.st_size:
                        raise ValueError(f"experiment file changed during export: {path}")
                    record = {"path": relative, "sha256": digest, "size_bytes": initial.st_size}
                    line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
                    index.write(line)
                    index_digest.update(line)
                    files += 1
                    logical_bytes += initial.st_size
                index_size = index.tell()
                index.seek(0)
                member = tarfile.TarInfo(INDEX)
                member.size, member.mode = index_size, 0o644
                archive.addfile(member, index)
                metadata = {"bundle_schema_version": 1, "original_root": str(root), "file_count": files,
                            "directory_count": directories,
                            "logical_bytes": logical_bytes, "source_unique_allocated_bytes": physical_bytes,
                            "index_sha256": index_digest.hexdigest(), "experiment_status": status["status"],
                            "integrity_scope": "all_retained_files_not_scientific_accuracy"}
                # Re-export preserves the reference root used by original JSON.
                if (root / METADATA).exists():
                    metadata["original_root"] = json.loads((root / METADATA).read_text())["original_root"]
                _tar_bytes(archive, METADATA, (json.dumps(metadata, sort_keys=True) + "\n").encode())
        output_handle.flush()
        os.fsync(output_handle.fileno())
    # Read the whole compressed stream to detect truncation/CRC damage before
    # committing. Import verification separately checks every payload digest.
    with gzip.open(temporary, "rb") as source:
        for _block in iter(lambda: source.read(1024 * 1024), b""):
            pass
    os.link(temporary, destination)  # exclusive commit: cannot replace a rival
    temporary.unlink()  # only this newly-created, verified temporary name
    return {"path": str(destination), "sha256": sha256_file(destination), "file_count": files,
            "logical_bytes": logical_bytes, "compressed_bytes": destination.stat().st_size,
            "source_unique_allocated_bytes": physical_bytes, "wall_seconds": time.monotonic() - started}


@serialized_run
def verify_import(directory: str | Path, *, verify_images: bool = False) -> dict:
    """Verify every imported original byte, including failures and extra files.

    Missing, modified, duplicate-indexed or unindexed payload files fail the
    audit. This does not assert scientific validity or restore runtime identity.
    """

    from .benchmark import sha256_file

    root = Path(directory).resolve()
    metadata = json.loads((root / METADATA).read_text())
    if metadata.get("bundle_schema_version") != 1:
        raise ValueError("unsupported portable bundle schema")
    if sha256_file(root / INDEX) != metadata["index_sha256"]:
        raise ValueError("portable index integrity failed")
    seen, directories, files, logical_bytes = set(), 0, 0, 0
    with (root / INDEX).open(encoding="utf-8") as index:
        for line in index:
            record = json.loads(line)
            relative = str(_relative(record["path"]))
            if relative in seen or relative in (INDEX, METADATA):
                raise ValueError("duplicate/reserved path in portable index")
            path = root / relative
            if record.get("kind") == "directory":
                if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(root):
                    raise ValueError(f"missing or unsafe imported directory: {relative}")
                directories += 1
                seen.add(relative)
                continue
            if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
                raise ValueError(f"missing or unsafe imported payload: {relative}")
            if path.stat().st_size != record["size_bytes"] or sha256_file(path) != record["sha256"]:
                raise ValueError(f"imported payload integrity failed: {relative}")
            seen.add(relative)
            files += 1
            logical_bytes += record["size_bytes"]
    actual = {path.relative_to(root).as_posix() for path in _entries(root)} - {INDEX, METADATA}
    if seen != actual or files != metadata["file_count"] or directories != metadata["directory_count"] or logical_bytes != metadata["logical_bytes"]:
        raise ValueError("portable payload inventory does not match original files")
    result = {"passed": True, "directory": str(root), "file_count": files, "directory_count": directories, "logical_bytes": logical_bytes,
              "original_root": metadata["original_root"], "classification": "retained_byte_integrity_only"}
    if verify_images:
        result["image_products"] = verify_import_images(root)
        result["passed"] = result["image_products"]["passed"]
    return result


def verify_import_images(directory: str | Path) -> dict:
    """Reconstruct saved image checks from imported masks and rebased references.

    Only image products with analysis manifests are checked here. A partial
    attempt without a manifest remains partial, not silently scientifically
    certified. No native magnetic/orbit backend is imported or rerun; this is
    not a cross-device comparison or complete scientific/runtime acceptance.
    """

    from .product_validation import validate_pipeline_images

    root = Path(directory).resolve()
    paths = PortablePaths(root)
    manifests, total_images, passed = [], 0, True
    for filename in sorted(root.rglob("manifest-*.json")):
        try:
            manifest = json.loads(filename.read_text())
            check = validate_pipeline_images(
                manifest, paths.resolve(manifest["raw_products_npz"]),
                tuple(paths.resolve(path) for path in manifest["plot_selection_files"]),
                path_resolver=paths.resolve,
            )
        except (ValueError, OSError, KeyError, TypeError) as exc:
            check = {"passed": False, "error": f"{type(exc).__name__}: {exc}", "images": []}
        manifests.append({"manifest": filename.relative_to(root).as_posix(), **check})
        total_images += len(check["images"])
        passed &= check["passed"]
    return {"passed": passed and bool(manifests), "status": "available" if manifests else "unavailable",
            "reason": None if manifests else "no retained analysis manifests",
            "pipeline_manifests": len(manifests), "images_checked": total_images,
            "scope": "saved_image_products_not_complete_attempt_acceptance", "checks": manifests}


@serialized_run
@serialized_run
@measured_operation("import", "directory", input_argument="bundle")
def import_experiment(bundle: str | Path, directory: str | Path, *, expected_sha256: str | None = None) -> dict:
    """Safely import and verify all records into a new directory, without clobber.

    No symlinks, devices, FIFOs, traversal or duplicate archive names are allowed.
    Only earlier internal regular files can be hard-link targets. If import
    fails, its explicit partial directory remains recoverable for inspection.
    """

    from .benchmark import sha256_file

    source, destination = Path(bundle).resolve(), Path(directory).resolve()
    if expected_sha256 is not None and sha256_file(source) != expected_sha256:
        raise ValueError("bundle SHA-256 does not match supplied transfer digest")
    destination.mkdir(parents=True, exist_ok=False)
    seen = set()
    with tarfile.open(source, mode="r|gz") as archive:
        for member in archive:
            name = str(_relative(member.name))
            if name in (INDEX, METADATA):
                relative = name
            elif name.startswith("payload/"):
                relative = str(_relative(name[len("payload/"):]))
                if relative in (INDEX, METADATA):
                    raise ValueError("payload collides with bundle envelope")
            else:
                raise ValueError(f"unexpected bundle member: {name}")
            if relative in seen:
                raise ValueError(f"duplicate bundle member: {name}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir() and name.startswith("payload/"):
                target.mkdir(exist_ok=True)
            elif member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"unreadable bundle member: {name}")
                with stream, target.open("xb") as output:
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(target, member.mode & 0o777)
            elif member.islnk() and name.startswith("payload/"):
                link = str(_relative(member.linkname))
                if not link.startswith("payload/"):
                    raise ValueError("hard link escapes bundle payload")
                link_relative = str(_relative(link[len("payload/"):]))
                linked = destination / link_relative
                if link_relative not in seen or linked.is_symlink() or not linked.is_file():
                    raise ValueError("hard-link target is not an earlier internal regular file")
                os.link(linked, target)
            else:
                raise ValueError(f"unsupported unsafe bundle member type: {name}")
            seen.add(relative)
    result = verify_import(destination)
    return {**result, "bundle_sha256": sha256_file(source)}


class PortablePaths:
    """Resolve retained references without editing their original JSON bytes."""

    def __init__(self, directory: str | Path):
        """Load an imported envelope, or use an experiment's current local root."""

        self.root = Path(directory).resolve()
        envelope = self.root / METADATA
        self.original_root = Path(json.loads(envelope.read_text())["original_root"]) if envelope.is_file() else self.root

    def resolve(self, reference: str | Path) -> Path:
        """Map internal absolute/relative references; reject external input paths.

        External original input/source names are provenance, not transferable
        files. Their compressed snapshots remain internal resolvable references.
        A historic plain-log reference can use its losslessly retained gzip.
        """

        path = Path(reference)
        relative = path.relative_to(self.original_root) if path.is_absolute() else Path(str(_relative(str(path))))
        target = self.root / relative
        if not target.resolve().is_relative_to(self.root):
            raise ValueError("retained reference escapes imported experiment")
        if not target.exists() and target.with_name(target.name + ".gz").is_file():
            return target.with_name(target.name + ".gz")
        return target
