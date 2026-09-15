import json
from pathlib import Path

from pcsuchai.full_validation import run_full_validation, verify_validation_certificate


ROOT = Path(__file__).parents[1]


def test_complete_workload_certificate_covers_all_backend_combinations(tmp_path: Path) -> None:
    plot_config = tmp_path / "plots.json"
    plot_config.write_text(json.dumps({"plots": [
        {"name": "full_validation_geographic", "coordinate_view": "geographic"},
        {"name": "full_validation_footpoint", "coordinate_view": "footpoint"},
    ]}))
    result = run_full_validation(
        tmp_path / "validation", ROOT,
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        ROOT / "data/eop/finals2000A.all",
        plot_config, symh_path=None, limit=5,
    )
    assert result["status"] == "pass"
    assert result["official_eligible"] is False
    assert result["full_code_workload"] is False
    assert result["validation_contract_version"] == 2 and len(result["criteria"]) == 15
    assert result["criteria"]["magnetic_reference_cases:aacgmv2"]["passed"]
    assert result["criteria"]["magnetic_reference_cases:apexpy"]["passed"]
    assert set(result["pipelines"]) == {
        "astropy-aacgmv2", "astropy-apexpy", "skyfield-aacgmv2", "skyfield-apexpy"
    }
    assert all(
        pipeline["criteria"]["single_process_order"]
        and pipeline["criteria"]["all_required_stages"]
        and pipeline["criteria"]["all_configured_plots"]
        for pipeline in result["pipelines"].values()
    )
    assert all(pipeline["image_validation"]["passed"] for pipeline in result["pipelines"].values())
    assert all(len(pipeline["image_validation"]["images"]) == 5 for pipeline in result["pipelines"].values())
    verification = verify_validation_certificate(
        result["certificate_path"], ROOT,
        ROOT / "data/raw/langmuir-2018-2.csv",
        ROOT / "data/tle/suchai1.tle",
        ROOT / "data/eop/finals2000A.all",
        plot_config, limit=5,
    )
    assert verification["passed"] is False
    assert verification["checks"]["full_code_workload"] is False
