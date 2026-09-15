"""Lossless retention of live samples, inputs, and repeated scientific products."""

from __future__ import annotations

import csv
import gzip
import hashlib
import os
import shutil
import tarfile
import time
import uuid
from pathlib import Path

from .benchmark import sha256_file


def compress_retained_file(path: Path, *, remove_original: bool = False) -> Path:
    """Create verified deterministic gzip; keep the source unless requested.

    The original is removed only after decompression reproduces its SHA-256.
    Interrupted compression leaves the original available. Existing archives
    are never overwritten. This function is called outside timed stages.
    """

    destination = path.with_name(path.name + ".gz")
    if destination.exists():
        raise FileExistsError(destination)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    expected = sha256_file(path)
    with path.open("rb") as source, temporary.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=6) as compressed:
            shutil.copyfileobj(source, compressed, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
    actual = hashlib.sha256()
    with gzip.open(temporary, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            actual.update(block)
    if actual.hexdigest() != expected:
        raise RuntimeError(f"lossless compression verification failed: {path}")
    os.replace(temporary, destination)
    if remove_original:
        path.unlink()
    return destination


class RawSampleJournal:
    """Stream CSV samples to disk, with at most one second between fsyncs.

    Every row is flushed immediately. An interrupted process retains its plain
    CSV; a successful recorder finalization replaces it with verified gzip.
    Nothing accumulates in memory. Logging errors are fatal, not suppressed.
    """

    def __init__(self, path: Path, fields: tuple[str, ...]) -> None:
        self.path = path
        self.fields = fields
        self.handle = None
        self.writer = None
        self.last_sync = 0.0

    def append(self, record: dict) -> None:
        """Persist one timestamped sample and periodically force it to storage."""

        if self.handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open("x", encoding="utf-8", newline="")
            self.writer = csv.DictWriter(self.handle, fieldnames=self.fields)
            self.writer.writeheader()
        self.writer.writerow({field: record.get(field) for field in self.fields})
        self.handle.flush()
        now = time.monotonic()
        if now - self.last_sync >= 1.0:
            os.fsync(self.handle.fileno())
            self.last_sync = now

    def sync(self) -> None:
        """Force all samples from the current stage to storage."""

        if self.handle is not None:
            self.handle.flush()
            os.fsync(self.handle.fileno())

    def finish(self) -> Path | None:
        """Close the live journal and retain every row in verified gzip."""

        if self.handle is None:
            return None
        self.sync()
        self.handle.close()
        self.handle = None
        return compress_retained_file(self.path, remove_original=True)


def snapshot_inputs(inputs: dict[str, Path], destination: Path) -> dict:
    """Retain one compressed byte-exact copy of each campaign input."""

    destination.mkdir(parents=True, exist_ok=False)
    records = {}
    for role, source in inputs.items():
        copy = destination / f"{role}-{source.name}"
        source_hash = sha256_file(source)
        shutil.copyfile(source, copy)
        if sha256_file(copy) != source_hash or sha256_file(source) != source_hash:
            raise RuntimeError(f"input changed during snapshot: {source}")
        original_size = copy.stat().st_size
        compressed = compress_retained_file(copy, remove_original=True)
        records[role] = {
            "path": str(compressed), "source_path": str(source),
            "source_sha256": source_hash,
            "source_size_bytes": original_size,
            "compressed_sha256": sha256_file(compressed),
        }
    return records


def snapshot_sources(root: Path, source_record: dict, destination: Path) -> dict:
    """Archive exactly the source files identified by the campaign digest."""

    with destination.open("xb") as output:
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for record in source_record["files"]:
                source = root / record["path"]
                if sha256_file(source) != record["sha256"]:
                    raise RuntimeError(f"source changed during snapshot: {source}")
                archive.add(source, arcname=record["path"], recursive=False)
        output.flush()
        os.fsync(output.fileno())
    # Verifying only the source before tar.add is insufficient: its bytes can
    # change while the tar reader is consuming it. Audit the actual archive
    # against every recorded digest before declaring a reproducible snapshot.
    expected = {record["path"]: record for record in source_record["files"]}
    seen = set()
    with tarfile.open(destination, "r:gz") as archive:
        for member in archive:
            if member.name not in expected or member.name in seen or not (member.isfile() or member.islnk()):
                raise RuntimeError(f"unexpected source snapshot member: {member.name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError(f"unreadable source snapshot member: {member.name}")
            digest, size = hashlib.sha256(), 0
            with stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            record = expected[member.name]
            if digest.hexdigest() != record["sha256"] or size != record["size_bytes"]:
                raise RuntimeError(f"source bytes changed during snapshot: {member.name}")
            seen.add(member.name)
    if seen != set(expected):
        raise RuntimeError("source snapshot is incomplete")
    for record in expected.values():
        if sha256_file(root / record["path"]) != record["sha256"]:
            raise RuntimeError(f"source changed before snapshot completed: {record['path']}")
    return {"path": str(destination), "sha256": sha256_file(destination)}


def deduplicate_products(products: Path, store: Path) -> dict:
    """Share byte-identical immutable products while preserving every run path.

    Each file's SHA-256 identifies its backing file. Hard-link replacement is
    atomic and does not change a single byte. Filesystems lacking hard links
    retain the original copies; they never cause data to be dropped. Completed
    products must not be edited in place, because linked runs share storage.
    """

    store.mkdir(parents=True, exist_ok=True)
    logical_bytes = 0
    new_content_bytes = 0
    shared_files = 0
    fallback_files = 0
    new_allocated_bytes = 0
    new_inodes = 0
    allocation_available = True
    for product in sorted(products.rglob("*")):
        if not product.is_file() or product.is_symlink():
            continue
        size = product.stat().st_size
        logical_bytes += size
        digest = sha256_file(product)
        stored = store / digest
        temporary = product.with_name(f".{product.name}.{uuid.uuid4().hex}.link")
        try:
            if not stored.exists():
                os.link(product, stored)
                new_content_bytes += size
                stat = product.stat()
                allocation_available &= hasattr(stat, "st_blocks")
                new_allocated_bytes += getattr(stat, "st_blocks", 0) * 512
                new_inodes += 1
                continue
            if sha256_file(stored) != digest:
                raise RuntimeError(f"retained artifact was modified: {stored}")
            if os.path.samefile(product, stored):
                continue
            os.link(stored, temporary)
            os.replace(temporary, product)
            shared_files += 1
        except OSError:
            # No loss of data on FAT/network/cross-device filesystems.
            fallback_files += 1
            new_content_bytes += size
            stat = product.stat()
            allocation_available &= hasattr(stat, "st_blocks")
            new_allocated_bytes += getattr(stat, "st_blocks", 0) * 512
            new_inodes += 1
            if temporary.exists():
                temporary.unlink()
    return {
        "mode": "lossless_sha256_hardlinks", "logical_product_bytes": logical_bytes,
        "new_content_bytes": new_content_bytes, "shared_files": shared_files,
        "fallback_files": fallback_files,
        "new_product_allocated_bytes": new_allocated_bytes if allocation_available else None,
        "new_product_inodes": new_inodes,
        "allocation_source": "st_blocks*512 for newly retained/fallback product inodes",
        "allocation_limit": "file blocks only; excludes directories, filesystem metadata and temporary peak",
    }
