from datetime import UTC, datetime, timedelta
from pathlib import Path

from pcsuchai.models import TLERecord
import pytest

from pcsuchai.errors import DataValidationError
from pcsuchai.tle import (
    audit_tle_history,
    load_tle_history,
    parse_tle_epoch,
    select_nearest_tles,
    tle_checksum,
)


ROOT = Path(__file__).parents[1]


def record(epoch: datetime) -> TLERecord:
    return TLERecord("line1", "line2", epoch, "42788")


def test_parses_tle_epoch() -> None:
    parsed = parse_tle_epoch("18106.50000000")
    assert parsed == datetime(2018, 4, 16, 12, tzinfo=UTC)


def test_loads_complete_suchai_history() -> None:
    records = load_tle_history(ROOT / "data/tle/suchai1.tle")
    assert len(records) == 4_462
    assert records[0].satellite_number == "42788"
    assert records == tuple(sorted(records, key=lambda item: item.epoch))
    assert all(tle_checksum(record.line1) == int(record.line1[-1]) for record in records)
    assert all(tle_checksum(record.line2) == int(record.line2[-1]) for record in records)


def test_nearest_selection_can_choose_later_tle() -> None:
    base = datetime(2018, 1, 1, tzinfo=UTC)
    records = (record(base), record(base + timedelta(hours=10)))
    observations = (base + timedelta(hours=7),)

    result = select_nearest_tles(observations, records)

    assert result.indices.tolist() == [1]
    assert result.offset_seconds.tolist() == [-3 * 3600]


def test_exact_tie_chooses_earlier_tle() -> None:
    base = datetime(2018, 1, 1, tzinfo=UTC)
    records = (record(base), record(base + timedelta(hours=10)))
    result = select_nearest_tles((base + timedelta(hours=5),), records)
    assert result.indices.tolist() == [0]


def test_rejects_corrupted_tle_checksum(tmp_path: Path) -> None:
    lines = (ROOT / "data/tle/suchai1.tle").read_text().splitlines()[:2]
    lines[0] = lines[0][:-1] + ("0" if lines[0][-1] != "0" else "1")
    path = tmp_path / "bad.tle"
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(DataValidationError, match="checksum"):
        load_tle_history(path)


def test_full_tle_audit_passes_measurement_coverage() -> None:
    from pcsuchai.data import load_measurements

    measurements = load_measurements(ROOT / "data/raw/langmuir-2018-2.csv")
    result = audit_tle_history(ROOT / "data/tle/suchai1.tle", measurements.times)
    assert result["status"] == "pass"
    assert result["records"] == 4462
    assert result["criteria"]["sgp4_at_epoch"]["passed"]
    assert result["assignment"]["later"] > 0
