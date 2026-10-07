"""One-file transfer tests with real export/receipt I/O, not Pi performance."""

import copy
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from pcsuchai.benchmark import sha256_file
from pcsuchai.experiment import ExperimentManifest
from pcsuchai.final_package import PACKAGE_METADATA, import_package, package_export
from pcsuchai.operation_costs import OperationCosts, report_operation_costs
from pcsuchai.portable import export_experiment, verify_import


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def finished(tmp_path, monkeypatch):
    """Actual closed export and two matched receipts; science is not invoked."""

    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "device.lock"))
    root = tmp_path / "benchmarks/pi5/2026/10/07/closed-test"
    root.mkdir(parents=True)
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    manifest = ExperimentManifest.from_dict(data)
    (root / "manifest.json").write_text(manifest.canonical_json)
    (root / "experiment-state.json").write_text(json.dumps({
        "status": "stopped", "manifest": data, "manifest_sha256": manifest.sha256,
        "device_label": "pi5", "source": {"sha256": "fixture-source-not-Pi-acceptance"},
        "segments": [], "blocks": []}))
    (root / "raw.partial.csv").write_bytes(b"utc,value\n2026-10-07,")
    (root / "failed-record.json").write_bytes(b'{"partial":')
    master = OperationCosts(root.parent / "operation-costs", "master-run",
        scope="master_post_stdlib_bootstrap_to_return",
        context={"experiment_directory": str(root), "manifest_sha256": manifest.sha256})
    master.finish(status="returned", outcome="stopped")
    bundle = tmp_path / "outputs/experiment-export.tar.gz"
    exported = export_experiment(root, bundle)
    return root, master.directory, bundle, Path(exported["operation_cost"]["directory"])


def test_single_file_roundtrip_keeps_archive_logs_and_originals(finished, tmp_path, monkeypatch):
    root, master, bundle, exported = finished
    before = {str(p): p.read_bytes() for source in (root, master, exported)
              for p in source.rglob("*") if p.is_file()}
    old_archive = bundle.read_bytes()
    receipt_count = len(list(tmp_path.rglob("intent.json")))
    import pcsuchai.pipeline as science
    monkeypatch.setattr(science, "run_analysis", lambda *a, **k: pytest.fail("packaging must never execute science"))
    packaged = package_export(bundle, tmp_path / "final.tar")
    assert packaged["scientific_rerun"] is False and packaged["receipt_count"] == 2
    assert len(list(tmp_path.rglob("intent.json"))) == receipt_count
    with tarfile.open(packaged["path"]) as archive:
        assert archive.extractfile("experiment.tar.gz").read() == old_archive
        metadata = json.load(archive.extractfile(PACKAGE_METADATA))
    assert metadata["experiment"]["experiment_id"] == root.name
    imported = import_package(packaged["path"], tmp_path / "imported", expected_sha256=packaged["sha256"])
    assert imported["passed"] and imported["scientific_rerun"] is False
    assert verify_import(imported["experiment_directory"])["passed"]
    imported_root = Path(imported["experiment_directory"])
    assert (imported_root / "raw.partial.csv").read_bytes() == (root / "raw.partial.csv").read_bytes()
    assert (imported_root / "failed-record.json").read_bytes() == (root / "failed-record.json").read_bytes()
    for original, role in ((master, "master"), (exported, "export")):
        copied = Path(imported["operation_costs_directory"]) / role / original.name
        for p in original.rglob("*"):
            if p.is_file():
                assert (copied / p.relative_to(original)).read_bytes() == p.read_bytes()
    costs = report_operation_costs([imported["operation_costs_directory"]], tmp_path / "cost-report")
    assert costs["counts"] == {"returned": 2, "raised": 0, "unfinished": 0, "invalid": 0}
    assert all(Path(p).read_bytes() == content for p, content in before.items())
    assert bundle.read_bytes() == old_archive


def test_unrelated_receipts_do_not_mix_and_resumes_are_retained(finished, tmp_path):
    root, master, bundle, _ = finished
    identity = json.loads((master / "intent.json").read_text())["context"]
    unrelated = OperationCosts(root.parent / "operation-costs", "master-run",
        scope="master_post_stdlib_bootstrap_to_return", context={**identity, "experiment_directory": str(root.parent / "another-test")})
    unrelated.finish(status="returned")
    resumed = OperationCosts(root.parent / "operation-costs", "master-resume",
        scope="master_post_stdlib_bootstrap_to_return", context=identity)
    # A genuine unfinished receipt is preserved as unfinished, never fabricated.
    packaged = package_export(bundle, tmp_path / "final.tar")
    assert packaged["receipt_count"] == 3
    with tarfile.open(packaged["path"]) as archive:
        names = archive.getnames()
        metadata = json.load(archive.extractfile(PACKAGE_METADATA))
    assert not any(unrelated.directory.name in name for name in names)
    assert any(resumed.directory.name in name for name in names)
    assert any(item["terminal_status"] == "unfinished" for item in metadata["receipts"])


@pytest.mark.parametrize("fault", ["missing-master", "missing-export", "master-manifest", "export-hash"])
def test_missing_or_mismatched_receipts_refuse_package(finished, tmp_path, fault):
    root, master, bundle, exported = finished
    if fault.startswith("missing"):
        roots = [exported] if fault == "missing-master" else [master]
    else:
        roots = [master, exported]
        path = master / "intent.json" if fault == "master-manifest" else exported / "terminal.json"
        value = json.loads(path.read_text())
        if fault == "master-manifest":
            value["context"]["manifest_sha256"] = "wrong"
        else:
            value["extra"]["returned_result"]["sha256"] = "wrong"
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        package_export(bundle, tmp_path / "refused.tar", receipt_roots=roots)
    assert not (tmp_path / "refused.tar").exists()
    assert root.is_dir() and bundle.is_file()


def test_exclusive_output_digest_and_destination_guards(finished, tmp_path):
    root, master, bundle, _ = finished
    output = tmp_path / "final.tar"
    package_export(bundle, output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        package_export(bundle, output)
    assert output.read_bytes() == before
    with pytest.raises(ValueError, match="SHA-256"):
        import_package(output, tmp_path / "not-created", expected_sha256="0" * 64)
    assert not (tmp_path / "not-created").exists()
    import_package(output, tmp_path / "imported")
    with pytest.raises(FileExistsError):
        import_package(output, tmp_path / "imported")
    for destination in (root / "nested.tar", master / "nested.tar"):
        with pytest.raises(ValueError, match="outside"):
            package_export(bundle, destination)
        assert not destination.exists()


def repack(source, target, transform):
    """Rewrite only a test-owned wrapper to inject malicious/tampered evidence."""

    with tarfile.open(source) as before, tarfile.open(target, "w") as after:
        for member in before:
            data = before.extractfile(member).read() if member.isfile() else None
            member, data = transform(copy.copy(member), data)
            if data is not None:
                member.size = len(data)
            after.addfile(member, io.BytesIO(data) if data is not None else None)


@pytest.mark.parametrize("fault", ["bytes", "cross-experiment", "unindexed", "duplicate", "traversal", "symlink"])
def test_tampered_or_unsafe_packages_fail_without_overwriting(finished, tmp_path, fault):
    _, _, bundle, _ = finished
    good = tmp_path / "good.tar"
    package_export(bundle, good)

    def damage(member, data):
        if member.name == PACKAGE_METADATA and fault == "cross-experiment":
            value = json.loads(data)
            value["experiment"]["manifest_sha256"] = "another-experiment"
            data = json.dumps(value).encode()
        if member.name == "experiment.tar.gz":
            if fault == "bytes": data = b"damaged"
            elif fault == "unindexed": member.name = "operation-costs/unindexed"
            elif fault == "traversal": member.name = "../outside"
            elif fault == "symlink":
                member.type, member.linkname, member.size, data = tarfile.SYMTYPE, "/outside", 0, None
        return member, data

    bad = tmp_path / "bad.tar"
    repack(good, bad, damage)
    if fault == "duplicate":
        with tarfile.open(bad, "a") as archive:
            member = tarfile.TarInfo("experiment.tar.gz")
            archive.addfile(member, io.BytesIO(b""))
    with pytest.raises(ValueError):
        import_package(bad, tmp_path / "partial")
    assert not (tmp_path / "outside").exists()
    assert good.is_file() and bundle.is_file()


def test_package_cli_is_one_extra_step_on_existing_files(finished, tmp_path):
    _, _, bundle, _ = finished
    output = tmp_path / "cli-final.tar"
    command = [sys.executable, str(ROOT / "scripts/run_experiment.py")]
    packaged = subprocess.run([*command, "package", str(bundle), "--output", str(output)],
                              capture_output=True, text=True, timeout=30)
    assert packaged.returncode == 0, packaged.stdout + packaged.stderr
    result = json.loads(packaged.stdout)
    assert result["scientific_rerun"] is False and result["sha256"] == sha256_file(output)
    unpacked = subprocess.run([*command, "import-package", str(output), str(tmp_path / "cli-imported"),
                               "--sha256", result["sha256"]], capture_output=True, text=True, timeout=30)
    assert unpacked.returncode == 0, unpacked.stdout + unpacked.stderr
    assert json.loads(unpacked.stdout)["passed"]


def test_copied_archive_uses_hash_and_original_identity_not_current_filename(finished, tmp_path):
    root, master, bundle, exported = finished
    copied = tmp_path / "copied-and-renamed.tar.gz"
    shutil.copyfile(bundle, copied)
    package = package_export(copied, tmp_path / "final.tar", receipt_roots=[master, exported])
    imported = import_package(package["path"], tmp_path / "imported")
    assert imported["passed"] and imported["experiment"]["original_root"] == str(root)


def test_publication_failure_keeps_originals_and_partial(finished, tmp_path, monkeypatch):
    import pcsuchai.final_package as module
    root, master, bundle, exported = finished
    originals = {p: p.read_bytes() for base in (root, master, exported) for p in base.rglob("*") if p.is_file()}
    original_archive = bundle.read_bytes()

    def cannot_publish(*args):
        raise OSError("test-owned publication failure")

    monkeypatch.setattr(module.os, "link", cannot_publish)
    with pytest.raises(OSError, match="publication failure"):
        package_export(bundle, tmp_path / "not-published.tar")
    assert not (tmp_path / "not-published.tar").exists()
    assert list(tmp_path.glob(".not-published.tar.*.partial"))
    assert bundle.read_bytes() == original_archive
    assert all(p.read_bytes() == value for p, value in originals.items())


def test_live_experiment_guard_never_starts_packaging(finished, tmp_path, monkeypatch):
    import pcsuchai.experiment_control as control
    _, _, bundle, _ = finished
    monkeypatch.setattr(control, "experiment_status", lambda root: {"live": True})
    with pytest.raises(ValueError, match="live"):
        package_export(bundle, tmp_path / "refused.tar")
    assert not (tmp_path / "refused.tar").exists()
