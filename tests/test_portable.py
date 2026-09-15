import gzip
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from pcsuchai.benchmark import sha256_file
from pcsuchai.portable import INDEX, METADATA, PortablePaths, export_experiment, import_experiment, verify_import


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    monkeypatch.setenv("PCSUCHAI_RUN_LOCK_PATH", str(tmp_path / "isolated-device.lock"))
    root = tmp_path / "original"
    root.mkdir()
    data = json.loads((ROOT / "configs/experiments/acceptance.json").read_text())
    (root / "experiment-state.json").write_text(json.dumps({"status": "stopped", "manifest": data,
                                                           "segments": [], "blocks": []}))
    first = root / "runs/2026-09-15/first"
    first.mkdir(parents=True)
    (first / "record.json").write_text(json.dumps({"path": str(first / "raw.csv.gz"), "status": "failed"}))
    with gzip.open(first / "raw.csv.gz", "wb") as output:
        output.write(b"utc,value\n2026-09-15,1\n")
    second = root / "runs/2026-09-15/second"
    second.mkdir()
    os.link(first / "raw.csv.gz", second / "raw.csv.gz")
    # Retain a partial sample and a torn JSON exactly, not only good summaries.
    (second / "raw.partial.csv").write_bytes(b"utc,value\n2026-09-15,")
    (second / "record.json").write_bytes(b'{"torn":')
    (root / "runs/2026-09-15/empty-interrupted-attempt").mkdir()
    return root


def test_bundle_roundtrip_preserves_all_raw_failures_sharing_and_references(experiment, tmp_path):
    before = {str(path.relative_to(experiment)): path.read_bytes() for path in experiment.rglob("*") if path.is_file()}
    bundle = tmp_path / "transfer.tar.gz"
    exported = export_experiment(experiment, bundle)
    imported = import_experiment(bundle, tmp_path / "imported", expected_sha256=exported["sha256"])
    assert imported["passed"] and imported["file_count"] == len(before)
    root = tmp_path / "imported"
    assert all((root / name).read_bytes() == contents for name, contents in before.items())
    assert (root / "runs/2026-09-15/empty-interrupted-attempt").is_dir()
    first, second = (root / f"runs/2026-09-15/{name}/raw.csv.gz" for name in ("first", "second"))
    assert first.stat().st_ino == second.stat().st_ino
    paths = PortablePaths(root)
    assert paths.resolve(experiment / "runs/2026-09-15/first/raw.csv") == first
    with pytest.raises(ValueError):
        paths.resolve("/outside/original-input.csv")
    assert verify_import(root)["classification"] == "retained_byte_integrity_only"
    again = export_experiment(root, tmp_path / "reexport.tar.gz")
    final = import_experiment(again["path"], tmp_path / "again")
    assert final["original_root"] == str(experiment)
    assert PortablePaths(tmp_path / "again").resolve(experiment / "experiment-state.json").is_file()
    from pcsuchai.operation_costs import report_operation_costs
    costs = report_operation_costs([tmp_path / "operation-costs"], tmp_path / "transfer-cost-audit")
    assert costs["counts"] == {"returned": 4, "raised": 0, "unfinished": 0, "invalid": 0}
    assert not list(root.rglob("operation-costs"))


def test_no_overwrite_and_transfer_digest_rejection(experiment, tmp_path):
    bundle = tmp_path / "transfer.tar.gz"
    export_experiment(experiment, bundle)
    digest = sha256_file(bundle)
    with pytest.raises(FileExistsError):
        export_experiment(experiment, bundle)
    assert sha256_file(bundle) == digest
    destination = tmp_path / "imported"
    with pytest.raises(ValueError, match="SHA-256"):
        import_experiment(bundle, destination, expected_sha256="0" * 64)
    assert not destination.exists()
    import_experiment(bundle, destination)
    with pytest.raises(FileExistsError):
        import_experiment(bundle, destination)


@pytest.mark.parametrize("damage", ["modified", "missing", "extra"])
def test_modified_missing_and_extra_payloads_are_not_verified(experiment, tmp_path, damage):
    bundle = tmp_path / "transfer.tar.gz"
    export_experiment(experiment, bundle)
    root = tmp_path / "imported"
    import_experiment(bundle, root)
    record = root / "runs/2026-09-15/second/record.json"
    if damage == "modified":
        record.write_bytes(b"damaged")
    elif damage == "missing":
        record.unlink()
    else:
        (root / "unindexed.txt").write_bytes(b"extra")
    with pytest.raises(ValueError):
        verify_import(root)


def test_duplicate_archive_names_are_rejected(experiment, tmp_path):
    bundle = tmp_path / "duplicate.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for _ in range(2):
            member = tarfile.TarInfo("payload/same.json")
            archive.addfile(member, io.BytesIO(b""))
    with pytest.raises(ValueError, match="duplicate"):
        import_experiment(bundle, tmp_path / "partial-duplicate")


@pytest.mark.parametrize("name,kind,link", [
    ("../escape", tarfile.REGTYPE, ""),
    ("payload/../escape", tarfile.REGTYPE, ""),
    ("/absolute", tarfile.REGTYPE, ""),
    ("payload/link", tarfile.SYMTYPE, "/outside"),
    ("payload/device", tarfile.CHRTYPE, ""),
    ("payload/hardlink", tarfile.LNKTYPE, "../../outside"),
    ("payload/hardlink", tarfile.LNKTYPE, "payload/not-yet-extracted"),
    ("payload/C:\\escape", tarfile.REGTYPE, ""),
    (f"payload/{METADATA}", tarfile.REGTYPE, ""),
])
def test_malicious_archive_paths_and_types_are_rejected(experiment, tmp_path, name, kind, link):
    bundle = tmp_path / "malicious.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type, member.linkname, member.size = kind, link, 0
        archive.addfile(member, io.BytesIO(b"") if kind == tarfile.REGTYPE else None)
    with pytest.raises(ValueError):
        import_experiment(bundle, tmp_path / "partial")
    assert (tmp_path / "partial").is_dir()  # failed imports remain inspectable
    assert not (tmp_path / "escape").exists()


def test_index_corruption_fails_verification(experiment, tmp_path):
    bundle = tmp_path / "transfer.tar.gz"
    export_experiment(experiment, bundle)
    root = tmp_path / "imported"
    import_experiment(bundle, root)
    (root / INDEX).write_text("{}\n")
    with pytest.raises(ValueError, match="index integrity"):
        verify_import(root)


def test_imported_images_use_retained_masks_without_original_paths(experiment, tmp_path):
    import numpy as np
    from PIL import Image

    products = experiment / "products"
    products.mkdir()
    image = products / "image.png"
    Image.new("RGB", (4, 2)).save(image)
    raw = products / "raw.npz"
    np.savez_compressed(raw, **{name: np.array([True]) for name in (
        "geographic_particle_map_mask", "magnetic_particle_map_mask", "footpoint_particle_map_mask")})
    # Declared fixture metadata tests path rebasing; this is not native
    # scientific/rendering acceptance or a claim about actual painted points.
    metadata = {"path": str(image), "points_rendered": 1, "width_px": 4, "height_px": 2,
                "rendering": {"filled_markers": True}, "geographic_context": {
                    "source": "bundled Natural Earth 110m", "land_parts": 1, "border_segments": 1}}
    (products / "manifest-test.json").write_text(json.dumps({
        "raw_products_npz": str(raw), "plot_selection_files": [],
        "plot": metadata, "magnetic_plot": metadata, "footpoint_plot": metadata}))
    bundle = tmp_path / "images.tar.gz"
    export_experiment(experiment, bundle)
    experiment.rename(tmp_path / "preserved-original")
    root = tmp_path / "imported"
    import_experiment(bundle, root)
    verified = verify_import(root, verify_images=True)
    assert verified["passed"] and verified["image_products"]["images_checked"] == 3
    assert all(Path(row["resolved_path"]).is_relative_to(root) for row in verified["image_products"]["checks"][0]["images"])
