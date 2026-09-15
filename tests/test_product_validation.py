from PIL import Image

from pcsuchai.product_validation import validate_image


def metadata(path):
    return {"path": str(path), "width_px": 40, "height_px": 20,
            "points_rendered": 3, "rendering": {"filled_markers": True},
            "geographic_context": {"source": "bundled Natural Earth 110m", "land_parts": 2, "border_segments": 3}}


def test_image_requires_decodable_png_dimensions_counts_and_context(tmp_path):
    path = tmp_path / "map.png"
    Image.new("RGB", (40, 20)).save(path)
    valid = metadata(path)
    assert validate_image(valid, 3, geographic=True)["passed"]
    assert not validate_image(valid, 4, geographic=True)["passed"]
    assert not validate_image({**valid, "width_px": 41}, 3, geographic=True)["passed"]
    assert not validate_image({**valid, "geographic_context": None}, 3, geographic=True)["passed"]
    assert not validate_image({**valid, "rendering": {"filled_markers": False}}, 3, geographic=True)["passed"]


def test_corrupt_or_missing_image_is_a_failed_saved_product(tmp_path):
    path = tmp_path / "corrupt.png"
    path.write_bytes(b"not an image")
    result = validate_image(metadata(path), 3, geographic=False)
    assert not result["passed"]
    assert not result["checks"]["png_readable"]
    assert "error" in result
    assert not validate_image(metadata(tmp_path / "missing.png"), 3, geographic=False)["passed"]
