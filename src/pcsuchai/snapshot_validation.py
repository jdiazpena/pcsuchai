"""Verify recorded source/input snapshots without running archived code.

Internal gzip/tar bytes bind historical provenance, independently of today's
checkout. Unknown/missing evidence does not establish controlled equivalence.
Only safe members are read into hash streams; none are extracted or executed.
"""

from __future__ import annotations

import gzip
import hashlib
import tarfile


def _stream_digest(handle) -> tuple[str, int]:
    """Hash actual bytes with bounded memory, including decompressed inputs."""

    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def verify_snapshots(state: dict, paths) -> dict:
    """Bind every frozen source member and input to its recorded SHA-256/size.

    Source-file ordering reproduces the version-1 digest contract, not current
    checkout bytes. Installed wheel/build provenance remains a separate audit.
    Original external paths are never accessed, including after portable import.
    """

    from .benchmark import sha256_file
    from .portable import _relative

    source = state["source"]
    digest, expected = hashlib.sha256(), {}
    for record in source["files"]:
        name = str(_relative(record["path"]))
        if name in expected:
            raise ValueError("duplicate frozen source member")
        expected[name] = record
        digest.update(name.encode() + b"\0" + record["sha256"].encode("ascii") + b"\n")
    if not expected or source.get("file_count") != len(expected) or digest.hexdigest() != source["sha256"]:
        raise ValueError("frozen source digest does not bind its member inventory")
    snapshot = state["source_snapshot"]
    filename = paths.resolve(snapshot["path"])
    if sha256_file(filename) != snapshot["sha256"]:
        raise ValueError("source snapshot archive integrity failed")
    seen = set()
    with tarfile.open(filename, "r:gz") as archive:
        for member in archive:
            if (member.name not in expected or member.name in seen or not (member.isfile() or member.islnk())
                    or (member.islnk() and member.linkname not in seen)):
                raise ValueError(f"unsafe/unexpected frozen source member/link: {member.name}")
            stream = archive.extractfile(member)
            with stream:
                actual, size = _stream_digest(stream)
            record = expected[member.name]
            if actual != record["sha256"] or size != record["size_bytes"]:
                raise ValueError(f"source snapshot member integrity failed: {member.name}")
            seen.add(member.name)
    if seen != expected.keys():
        raise ValueError("source snapshot members incomplete")
    return _verify_inputs(state, paths, expected)


def _verify_inputs(state, paths, source_members) -> dict:
    """Bind named input gzip snapshots and return internal measurement/TLE paths."""

    from .benchmark import sha256_file
    from .experiment_runner import safe_name

    resolved = {}
    for key, record in state["inputs"].items():
        snapshot_key = f"{safe_name(key)}-{hashlib.sha256(key.encode()).hexdigest()[:8]}"
        snapshot = state["input_snapshots"][snapshot_key]
        filename = paths.resolve(snapshot["path"])
        if sha256_file(filename) != snapshot["compressed_sha256"]:
            raise ValueError(f"compressed input snapshot integrity failed: {key}")
        with gzip.open(filename, "rb") as handle:
            actual, size = _stream_digest(handle)
        if (actual != record["sha256"] or actual != snapshot["source_sha256"]
                or size != record["size_bytes"] or size != snapshot["source_size_bytes"]):
            raise ValueError(f"input snapshot bytes do not bind frozen provenance: {key}")
        resolved[key] = filename
    return {"passed": True, "input_paths": resolved, "source_member_count": len(source_members),
            "scope": "all_frozen_source_and_input_bytes_not_installed_binaries_or_absolute_science"}
