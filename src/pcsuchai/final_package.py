"""One-file final handoff of an existing export and its matching receipts.

No scientific work is executed. The compressed export is stored unchanged in
an uncompressed tar wrapper, alongside only its own master/export logs. Original
files remain untouched. Package metadata binds every file by SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .benchmark import sha256_file
from .campaign_costs import cost_clock
from .experiment import ExperimentManifest
from .portable import METADATA, _entries, _relative, _tar_bytes, import_experiment
from .run_lock import serialized_run
from .saved_attempts import _json, _json_text


PACKAGE_METADATA = "package.json"
ARCHIVE_MEMBER = "experiment.tar.gz"


def _export_identity(bundle: Path) -> dict:
    """Read archived identity, not today's mutable checkout or experiment state."""

    wanted = {METADATA, "payload/manifest.json", "payload/experiment-state.json"}
    documents = {}
    with tarfile.open(bundle, "r|gz") as archive:
        for member in archive:
            if member.name not in wanted:
                continue
            if member.name in documents or not member.isfile() or member.size > 32 * 1024 * 1024:
                raise ValueError("invalid or duplicate experiment identity document")
            with archive.extractfile(member) as source:
                documents[member.name] = _json_text(source.read().decode("utf-8"), member.name)
    if documents.keys() != wanted:
        raise ValueError("export lacks its metadata, manifest or experiment state")
    envelope = documents[METADATA]
    state = documents["payload/experiment-state.json"]
    manifest = ExperimentManifest.from_dict(documents["payload/manifest.json"])
    original = envelope.get("original_root")
    if envelope.get("bundle_schema_version") != 1 or not isinstance(original, str) or not Path(original).is_absolute():
        raise ValueError("invalid exported experiment root")
    if state.get("manifest_sha256") != manifest.sha256 or state.get("manifest") != manifest.data:
        raise ValueError("archived experiment and manifest identities disagree")
    return {"original_root": original, "experiment_id": Path(original).name,
            "manifest_sha256": manifest.sha256, "device_label": state.get("device_label"),
            "source_sha256": state.get("source", {}).get("sha256"),
            "recorded_status": state.get("status")}


def _receipt_binding(directory: Path, identity: dict, archive_path: str | None, archive_sha256: str) -> dict | None:
    """Associate a receipt with this experiment or this exact completed export."""

    intent = _json(directory / "intent.json")
    context = intent.get("context", {})
    operation = intent.get("operation")
    if operation in ("master-run", "master-resume"):
        if context.get("experiment_directory") != identity["original_root"]:
            return None
        if context.get("manifest_sha256") != identity["manifest_sha256"]:
            raise ValueError("matching master receipt has a different manifest")
        role = "master"
    elif operation == "export":
        if archive_path is not None and context.get("output_path") != archive_path:
            return None
        if context.get("input_paths") != [identity["original_root"]]:
            return None
        role = "export"
    else:
        return None
    if intent.get("operation_id") != directory.name:
        raise ValueError(f"operation receipt identity mismatch: {directory}")
    terminal_path = directory / "terminal.json"
    terminal = _json(terminal_path) if terminal_path.exists() else None
    if terminal is not None and terminal.get("operation_id") != directory.name:
        raise ValueError("operation terminal identity mismatch")
    if role == "export":
        if terminal is None or terminal.get("status") != "returned":
            return None
        result = (terminal.get("extra") or {}).get("returned_result") or {}
        if result.get("sha256") != archive_sha256:
            return None
        if result.get("path") != context.get("output_path"):
            raise ValueError("completed export receipt does not match archive bytes")
    binding = {"role": role, "operation_id": directory.name,
            "original_directory": str(directory),
            "member_directory": f"operation-costs/{role}/{directory.name}",
            "terminal_status": terminal.get("status") if terminal else "unfinished"}
    if role == "export":
        binding["archive_original_path"] = context["output_path"]
    return binding


def _find_receipts(roots, identity, digest):
    """Find matching run/resume receipts and exactly one successful export log."""

    found = {}
    for root in dict.fromkeys(Path(path).resolve() for path in roots):
        if not root.is_dir():
            continue
        for intent in sorted(root.rglob("intent.json")):
            if intent.is_symlink() or not intent.resolve().is_relative_to(root):
                raise ValueError("linked receipt is not allowed in a final package")
            binding = _receipt_binding(intent.parent, identity, None, digest)
            if binding is not None:
                found[intent.parent.resolve()] = binding
    receipts = [(path, binding) for path, binding in sorted(found.items())]
    if not any(binding["role"] == "master" for _, binding in receipts):
        raise ValueError("no matching master receipt found; supply its folder with --receipt-root")
    if sum(binding["role"] == "export" for _, binding in receipts) != 1:
        raise ValueError("expected exactly one matching completed export receipt; supply --receipt-root")
    return receipts


@serialized_run
def package_export(bundle: str | Path, output: str | Path, *, receipt_roots=None) -> dict:
    """Wrap finished files once, preserving originals and refusing overwrite.

    No additional external operation receipt is created for this final wrapper.
    Its preparation/payload-copy cost is recorded inside package.json; the
    explicitly excluded trailer, verification and publication cannot measure
    their own final completion inside the immutable file they finish creating.
    """

    started = cost_clock()
    source, destination = Path(bundle).resolve(), Path(output).resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    identity = _export_identity(source)
    original = Path(identity["original_root"])
    if original.exists():
        from .experiment_control import experiment_status
        if experiment_status(original)["live"]:
            raise ValueError("stop the verified live experiment before packaging")
    digest = sha256_file(source)
    roots = receipt_roots if receipt_roots is not None else [original.parent / "operation-costs", source.parent / "operation-costs"]
    receipts = _find_receipts(roots, identity, digest)
    if destination.is_relative_to(original) or any(destination.is_relative_to(path) for path, _ in receipts):
        raise ValueError("final package must be outside its immutable experiment and receipt folders")
    inputs = [(source, ARCHIVE_MEMBER)]
    for path, binding in receipts:
        inputs.extend((child, f"{binding['member_directory']}/{child.relative_to(path).as_posix()}")
                      for child in _entries(path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent)
    temporary = Path(name)
    records, names = [], set()
    with os.fdopen(descriptor, "wb") as output_handle:
        with tarfile.open(fileobj=output_handle, mode="w|") as archive:
            for path, relative in inputs:
                _relative(relative)
                if relative in names or relative == PACKAGE_METADATA:
                    raise ValueError("duplicate final package member")
                names.add(relative)
                if path.is_symlink():
                    raise ValueError("linked package source is not allowed")
                member = archive.gettarinfo(str(path), arcname=relative)
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = ""
                if path.is_dir():
                    archive.addfile(member)
                    records.append({"name": relative, "kind": "directory"})
                else:
                    initial = path.stat()
                    before = sha256_file(path)
                    member.type, member.linkname, member.size = tarfile.REGTYPE, "", initial.st_size
                    with path.open("rb") as handle:
                        archive.addfile(member, handle)
                    if sha256_file(path) != before or path.stat().st_size != initial.st_size:
                        raise ValueError(f"source changed during final packaging: {path}")
                    if relative == ARCHIVE_MEMBER and before != digest:
                        raise ValueError("archive changed after receipt association")
                    records.append({"name": relative, "kind": "file", "size_bytes": initial.st_size, "sha256": before})
            ended = cost_clock()
            metadata = {"package_schema_version": 1, "package_type": "pcsuchai-final-evidence",
                        "created_utc": datetime.now(timezone.utc).isoformat(), "experiment": identity,
                        "archive_original_path": next(binding["archive_original_path"] for _, binding in receipts if binding["role"] == "export"),
                        "archive_source_path": str(source), "archive_sha256": digest,
                        "receipts": [binding for _, binding in receipts], "members": records,
                        "scientific_rerun": False, "originals_retained": True,
                        "storage": "uncompressed tar wrapper; existing gzip/PNG/NPZ bytes unchanged",
                        "packaging_cost": {"started": started, "ended": ended,
                            "wall_seconds": ended["monotonic_seconds"] - started["monotonic_seconds"],
                            "parent_process_cpu_seconds": ended["process_cpu_seconds"] - started["process_cpu_seconds"],
                            "scope": "preparation_and_payload_copy_excludes_metadata_trailer_verification_and_publication"}}
            _tar_bytes(archive, PACKAGE_METADATA, (json.dumps(metadata, sort_keys=True, allow_nan=False) + "\n").encode())
        output_handle.flush()
        os.fsync(output_handle.fileno())
    _check_package(temporary)
    os.link(temporary, destination)
    temporary.unlink()  # Only this new verified temporary, never original evidence.
    return {"path": str(destination), "sha256": sha256_file(destination),
            "size_bytes": destination.stat().st_size, "experiment": identity,
            "receipt_count": len(receipts), "scientific_rerun": False, "originals_retained": True,
            "packaging_cost": metadata["packaging_cost"]}


def _check_package(source: Path, destination: Path | None = None) -> dict:
    """Stream-check a wrapper; optionally copy safe members to a new directory."""

    observed, metadata = {}, None
    with tarfile.open(source, "r|*") as archive:
        for member in archive:
            relative = str(_relative(member.name))
            if relative in observed or (relative == PACKAGE_METADATA and metadata is not None):
                raise ValueError("duplicate final package member")
            if relative == PACKAGE_METADATA:
                if not member.isfile() or member.size > 32 * 1024 * 1024:
                    raise ValueError("invalid final package metadata")
                with archive.extractfile(member) as handle:
                    metadata = _json_text(handle.read().decode("utf-8"), PACKAGE_METADATA)
                if destination is not None:
                    with (destination / PACKAGE_METADATA).open("xb") as handle:
                        handle.write((json.dumps(metadata, sort_keys=True, allow_nan=False) + "\n").encode())
                continue
            if relative != ARCHIVE_MEMBER and not relative.startswith("operation-costs/"):
                raise ValueError("unexpected final package member")
            if not member.isdir() and not member.isfile():
                raise ValueError("unsafe final package member type")
            target = destination / relative if destination is not None else None
            if member.isdir():
                if target is not None:
                    target.mkdir(parents=True, exist_ok=True)
                observed[relative] = {"name": relative, "kind": "directory"}
                continue
            digest, size = hashlib.sha256(), 0
            if target is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as handle:
                output = target.open("xb") if target is not None else None
                try:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
                        if output is not None:
                            output.write(block)
                    if output is not None:
                        output.flush()
                        os.fsync(output.fileno())
                finally:
                    if output is not None:
                        output.close()
            observed[relative] = {"name": relative, "kind": "file", "size_bytes": size, "sha256": digest.hexdigest()}
    if not metadata or metadata.get("package_schema_version") != 1 or metadata.get("package_type") != "pcsuchai-final-evidence":
        raise ValueError("missing or invalid final package metadata")
    members = metadata.get("members")
    if not isinstance(members, list) or len(members) != len(observed):
        raise ValueError("final package inventory mismatch")
    expected = {}
    for record in members:
        name = str(_relative(record["name"]))
        if name in expected:
            raise ValueError("duplicate final package inventory entry")
        expected[name] = record
    if expected != observed or observed.get(ARCHIVE_MEMBER, {}).get("sha256") != metadata.get("archive_sha256"):
        raise ValueError("final package file integrity mismatch")
    if not isinstance(metadata.get("receipts"), list) or not metadata["receipts"]:
        raise ValueError("final package lacks matching operation logs")
    return metadata


@serialized_run
def import_package(bundle: str | Path, directory: str | Path, *, expected_sha256: str | None = None) -> dict:
    """Verify/unpack one final file and import its original experiment unchanged.

    The container has separate transfer/experiment subdirectories, so unpacking
    cannot invalidate the original export's immutable inventory. Partial failed
    imports are kept. No science executes and no existing destination is reused.
    """

    source, destination = Path(bundle).resolve(), Path(directory).resolve()
    if expected_sha256 is not None and sha256_file(source) != expected_sha256:
        raise ValueError("final package SHA-256 does not match supplied transfer digest")
    destination.mkdir(parents=True, exist_ok=False)
    transfer = destination / "transfer"
    transfer.mkdir()
    metadata = _check_package(source, transfer)
    identity = _export_identity(transfer / ARCHIVE_MEMBER)
    if identity != metadata.get("experiment"):
        raise ValueError("final package belongs to a different archived experiment")
    expected_dirs = set()
    for binding in metadata["receipts"]:
        directory_name = str(_relative(binding["member_directory"]))
        if directory_name != f"operation-costs/{binding['role']}/{binding['operation_id']}" or directory_name in expected_dirs:
            raise ValueError("invalid or duplicate packaged receipt directory")
        expected_dirs.add(directory_name)
        actual = _receipt_binding(transfer / directory_name, identity, metadata["archive_original_path"], metadata["archive_sha256"])
        if actual is None or any(actual[key] != binding[key] for key in ("role", "operation_id", "member_directory", "terminal_status")):
            raise ValueError("packaged operation log belongs to another experiment/export")
    if sum(item["role"] == "export" for item in metadata["receipts"]) != 1 or not any(item["role"] == "master" for item in metadata["receipts"]):
        raise ValueError("incomplete final package operation logs")
    for record in metadata["members"]:
        if record["name"] != ARCHIVE_MEMBER and not any(record["name"].startswith(prefix + "/") for prefix in expected_dirs):
            raise ValueError("unassociated operation files in final package")
    result = import_experiment(transfer / ARCHIVE_MEMBER, destination / "experiment", expected_sha256=metadata["archive_sha256"])
    return {"passed": result["passed"], "directory": str(destination),
            "experiment_directory": str(destination / "experiment"),
            "operation_costs_directory": str(transfer / "operation-costs"),
            "package_sha256": sha256_file(source), "experiment": identity,
            "receipt_count": len(metadata["receipts"]), "scientific_rerun": False}
