from pcsuchai.install_report import create_installation_report


def test_local_apex_installation_has_native_extension() -> None:
    result = create_installation_report()
    assert result["status"] == "pass"
    assert result["apexpy_extensions"]
    assert all(not item["missing_dependency"] for item in result["apexpy_extensions"])
