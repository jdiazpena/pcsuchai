from collections import Counter
from pathlib import Path

import pytest

from pcsuchai.experiment import ExperimentManifest, balanced_order, thread_environment


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path", sorted((ROOT / "configs/experiments").glob("*.json")))
def test_all_named_protocols_have_complete_contracts(path):
    manifest = ExperimentManifest.load(path)
    assert manifest.sha256 == ExperimentManifest.from_dict(manifest.data).sha256
    copy = manifest.data
    copy["execution"]["stop"]["value"] = 999
    assert manifest.data["execution"]["stop"]["value"] != 999


@pytest.mark.parametrize("section,key,value", [
    (None, "ignored_option", 1),
    ("execution", "retry_until_success", True),
    ("execution", "warmups", True),
    ("execution", "timeout_seconds", float("nan")),
    ("execution", "threads", "guess"),
    ("retention", "mode", "summaries_only"),
    ("validation", "allow_version_drift", True),
])
def test_unsupported_or_ambiguous_requests_fail_before_execution(section, key, value):
    data = ExperimentManifest.load(ROOT / "configs/experiments/equal-work.json").data
    (data if section is None else data[section])[key] = value
    with pytest.raises(ValueError):
        ExperimentManifest.from_dict(data)


def test_equal_work_cannot_accidentally_use_duration_or_uncontrolled_thermal():
    data = ExperimentManifest.load(ROOT / "configs/experiments/equal-work.json").data
    data["execution"]["stop"]["kind"] = "duration_per_pair_seconds"
    with pytest.raises(ValueError, match="fixed attempts"):
        ExperimentManifest.from_dict(data)
    data["execution"]["stop"]["kind"] = "attempts_per_pair"
    data["thermal"]["mode"] = "uncontrolled"
    data["thermal"]["policy"] = None
    with pytest.raises(ValueError, match="recovery before each attempt"):
        ExperimentManifest.from_dict(data)


def test_counter_groups_cannot_mix_user_and_kernel_scopes():
    data = ExperimentManifest.load(ROOT / "configs/experiments/counters.json").data
    data["observation"]["counter_groups"] = [["cycles:u", "instructions:k"]]
    with pytest.raises(ValueError, match="same scope"):
        ExperimentManifest.from_dict(data)


def test_balanced_round_cycle_has_exact_position_balance():
    pairs = ["a", "b", "c", "d"]
    orders = [balanced_order(pairs, 1, i, 42) for i in range(1, 5)]
    for position in range(4):
        assert Counter(order[position] for order in orders) == Counter(pairs)
    assert balanced_order(pairs, 2, 1, 42) == orders[1]
    assert pairs == ["a", "b", "c", "d"]


def test_thread_baseline_is_declared_and_stock_keeps_original():
    original = {"OPENBLAS_NUM_THREADS": "4", "PATH": "/usr/bin"}
    assert thread_environment("stock", original) == original
    assert thread_environment("one", original)["OPENBLAS_NUM_THREADS"] == "1"
    assert original["OPENBLAS_NUM_THREADS"] == "4"


def test_required_sensor_is_explicit_and_false_default_preserves_legacy_hash():
    data = ExperimentManifest.load(ROOT / "configs/experiments/sustained.json").data
    original = ExperimentManifest.from_dict(data).sha256
    assert "require_temperature_sensor" not in data["thermal"]
    assert ExperimentManifest.from_dict(data).sha256 == original
    data["thermal"]["require_temperature_sensor"] = True
    data["thermal"]["maximum_temperature_c"] = None
    assert ExperimentManifest.from_dict(data).data["thermal"]["require_temperature_sensor"] is True
    data["thermal"]["require_temperature_sensor"] = 1
    with pytest.raises(ValueError, match="must be boolean"):
        ExperimentManifest.from_dict(data)
