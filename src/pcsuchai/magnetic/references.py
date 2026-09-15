"""Frozen upstream regressions and explicitly same-library production bridges.

These checks detect implementation/configuration regressions, not independent
physical accuracy. Every acquired value is retained, including failed cases.
No magnetic backend is imported until its own checks are requested.
"""

from __future__ import annotations

import importlib
import math
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np

from ..benchmark import sha256_file
from ..models import OrbitResult, MagneticResult
from .factory import convert_magnetic
from .integrity import audit_magnetic_result


CASE_SOURCE = "src/pcsuchai/assets/magnetic-reference-cases.json"
MODULE_SOURCE = "src/pcsuchai/magnetic/references.py"
FIELDS = ("latitude_deg", "longitude_deg", "local_time_hours", "surface_latitude_deg",
          "surface_longitude_deg", "surface_altitude_km", "mapping_error_deg", "error_codes")
UNITS = ("degree", "degree", "hour", "degree", "degree", "geodetic_km", "angular_residual_degree", "code")


def load_reference_cases() -> dict:
    """Read packaged, version-specific expected data without online access."""

    from ..saved_attempts import _json
    return _json(Path(__file__).parents[1] / "assets/magnetic-reference-cases.json")


def _numbers(values) -> list:
    """Represent unavailable native floats as null, never a fake numeric zero."""

    return [float(value) if math.isfinite(float(value)) else None for value in np.asarray(values).reshape(-1)]


def _raw_numbers(values) -> dict:
    """Keep exact float64 bytes alongside nullable presentation, including NaN/inf."""

    array = np.asarray(values, dtype="<f8").reshape(-1)
    return {"values": _numbers(array), "float64_little_endian_hex": array.tobytes().hex()}


def _verify_raw_numbers(item: dict, name: str = "actual") -> bool:
    """Verify nullable display against retained IEEE bytes, not invented zeros."""

    raw = bytes.fromhex(item[f"{name}_float64_little_endian_hex"])
    return len(raw) == 8 * len(item[name]) and item[name] == _numbers(np.frombuffer(raw, dtype="<f8"))


def _comparison(actual: list, expected: list, tolerance: dict) -> dict:
    """Replay finite numeric bounds and exact null patterns with declared units."""

    passed, deltas = len(actual) == len(expected), []
    for value, target in zip(actual, expected):
        if target is None or value is None:
            passed &= target is None and value is None
            deltas.append(None)
            continue
        if isinstance(value, bool) or isinstance(target, bool) or not all(
                isinstance(item, (int, float)) and math.isfinite(item) for item in (value, target)):
            passed = False
            deltas.append(None)
            continue
        delta = abs(value - target)
        bound = tolerance["atol"] + tolerance["rtol"] * abs(target)
        passed &= delta < bound if tolerance["strict"] else delta <= bound
        deltas.append(delta)
    return {"passed": bool(passed), "absolute_deltas": deltas}


def _native_anchor(module, backend: str, case: dict) -> object:
    """Run only the published operation/epoch/height, not production defaults."""

    if backend == "apexpy":
        converter = module.Apex(date=case["epoch_decimal_year"], refh=case["refh_km"])
        if case["operation"] not in {"map_to_height", "geo2apex", "apex2geo"}:
            raise ValueError("unsupported frozen Apex reference operation")
        return getattr(converter, case["operation"])(*case["args"])
    timestamp = datetime.fromisoformat(case["utc"])
    if case["operation"] == "convert_mlt":
        return module.convert_mlt(case["args"][0], timestamp, m2a=True)
    return module.convert_latlon(*case["args"], timestamp, method_code=case["method"])


def _bridge_expected(module, backend: str, case: dict) -> list:
    """Calculate a same-library oracle for the separately labelled API bridge."""

    if case["orbit_error"] or case.get("expected_error"):
        return [None] * 7 + [2 if case["orbit_error"] else case["expected_error"]]
    timestamp = datetime.fromisoformat(case["utc"])
    lat, lon, height = case["position"]
    if backend == "apexpy":
        converter = module.Apex(date=timestamp, refh=0)
        mlat, mlon = converter.geo2apex(lat, lon, height)
        mlt = converter.mlon2mlt(mlon, timestamp)
        slat, slon, error = converter.map_to_height(lat, lon, height, 0)
        return _numbers([mlat, mlon, mlt, slat, slon, 0, error, 0])
    mlat, mlon, _ = module.convert_latlon(lat, lon, height, timestamp, method_code="G2A|ALLOWTRACE")
    mlt = module.convert_mlt(mlon, timestamp)[0]
    slat, slon, altitude = module.convert_latlon(mlat, mlon, 0, timestamp, method_code="A2G|ALLOWTRACE")
    return _numbers([mlat, mlon, mlt, slat, slon, altitude, np.nan, 0])


def _production_bridge(module, backend: str, case: dict, tolerance: dict) -> dict:
    """Exercise the real factory and verify every output, mask and frame label."""

    timestamp = datetime.fromisoformat(case["utc"])
    lat, lon, height = case["position"]
    orbit = OrbitResult(np.array([lat]), np.array([lon]), np.array([height]),
                        np.array([case["orbit_error"]], dtype=np.int16), "reference-WGS84-input")
    expected = _bridge_expected(module, backend, case)
    result = convert_magnetic(backend, (timestamp,), orbit)
    acquired = _raw_numbers([getattr(result, name)[0] for name in FIELDS])
    actual = acquired["values"]
    comparison = _comparison(actual, expected, tolerance)
    invariants = audit_magnetic_result(result, orbit)
    comparison["passed"] &= invariants["passed"] and result.backend == backend
    return {"definition": case, "fields": list(FIELDS), "units": list(UNITS), "expected": expected,
            "actual": actual, "actual_float64_little_endian_hex": acquired["float64_little_endian_hex"],
            "actual_backend": result.backend, "actual_coordinate_system": result.coordinate_system,
            "comparison": comparison, "invariants": invariants}


def _native_provenance(module, backend: str) -> list:
    """Hash actual installed binaries and configured coefficient files used here.

    AACGM's configured prefix may reside outside its package. Record all files
    matching that prefix, rather than silently assuming bundled coefficients.
    These hashes are build/data identities, not expected science values.
    """

    paths = {Path(module.__file__)} | set(Path(module.__file__).parent.glob("*.so"))
    if backend == "apexpy":
        converter = module.Apex(date=2000, refh=300)
        paths.update(Path(name) for name in (converter.datafile, converter.igrf_fn, converter.fortranlib))
    else:
        prefix = Path(module.AACGM_v2_DAT_PREFIX)
        paths.update(prefix.parent.glob(prefix.name + "*"))
        paths.add(Path(module.IGRF_COEFFS))
    return [{"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in sorted(paths) if path.is_file()]


def validate_magnetic_reference_cases(backend: str) -> dict:
    """Retain all fixed anchors/bridges; unavailable or changed versions fail closed."""

    definitions = load_reference_cases()
    if backend not in definitions["models"]:
        raise ValueError(f"unknown magnetic reference backend: {backend}")
    model, bridges = definitions["models"][backend], definitions["production_bridge"]
    report = {"schema_version": 1, "backend": backend, "scope": definitions["scope"],
              "definition": model, "bridge_definition": bridges,
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "version_expected": model["version"], "version_actual": None,
              "anchors": [], "production_bridges": [], "status": "fail"}
    try:
        module = importlib.import_module(backend)
        report["version_actual"] = version(backend)
        report["native_files"] = _native_provenance(module, backend)
    except (ImportError, OSError, ValueError, RuntimeError, AttributeError, TypeError, OverflowError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    for case in model["cases"]:
        item = {"definition": case, "actual": None, "comparison": {"passed": False}}
        try:
            acquired = _raw_numbers(_native_anchor(module, backend, case))
            item["actual"] = acquired["values"]
            item["actual_float64_little_endian_hex"] = acquired["float64_little_endian_hex"]
            item["comparison"] = _comparison(item["actual"], case["expected"], model["tolerance"])
        except (ValueError, RuntimeError, OverflowError, OSError, TypeError, AttributeError) as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        report["anchors"].append(item)
    for case in bridges["cases"]:
        if case.get("backend", backend) != backend:
            continue
        try:
            item = _production_bridge(module, backend, case, bridges["tolerance"])
        except (ValueError, RuntimeError, OverflowError, OSError, TypeError, AttributeError) as exc:
            item = {"definition": case, "actual": None, "comparison": {"passed": False},
                    "error": f"{type(exc).__name__}: {exc}"}
        report["production_bridges"].append(item)
    report["status"] = "pass" if report["version_actual"] == model["version"] and all(
        item["comparison"]["passed"] for item in report["anchors"] + report["production_bridges"]) else "fail"
    return report


def audit_reference_report(report: dict, definitions: dict, backend: str) -> bool:
    """Replay archived raw results against archived fixed oracles without imports.

    This is retained-byte/software evidence, not authentication of self-signed
    archives. Same-library bridge expected values are explicitly not goldens.
    """

    try:
        model, bridges = definitions["models"][backend], definitions["production_bridge"]
        if not (report["schema_version"] == 1 and report["backend"] == backend and report["status"] == "pass"
                and report["scope"] == definitions["scope"] and report["definition"] == model
                and report["bridge_definition"] == bridges
                and report["version_expected"] == report["version_actual"] == model["version"]):
            return False
        native_files = report["native_files"]
        if not isinstance(native_files, list) or not native_files or len({item["path"] for item in native_files}) != len(native_files):
            return False
        if any(not isinstance(item["path"], str) or not item["path"] or type(item["size_bytes"]) is not int
               or item["size_bytes"] <= 0 or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64
               or any(char not in "0123456789abcdef" for char in item["sha256"]) for item in native_files):
            return False
        if len(report["anchors"]) != len(model["cases"]):
            return False
        for item, case in zip(report["anchors"], model["cases"]):
            if item.get("error") or item["definition"] != case or not _verify_raw_numbers(item) or item["comparison"] != _comparison(
                    item["actual"], case["expected"], model["tolerance"]) or not item["comparison"]["passed"]:
                return False
        cases = [case for case in bridges["cases"] if case.get("backend", backend) == backend]
        if len(report["production_bridges"]) != len(cases):
            return False
        for item, case in zip(report["production_bridges"], cases):
            if item.get("error") or item["definition"] != case or not _verify_raw_numbers(item) or item["fields"] != list(FIELDS) or item["units"] != list(UNITS):
                return False
            expected = item["expected"]
            if len(expected) != len(FIELDS) or expected[-1] != (2 if case["orbit_error"] else case.get("expected_error", 0)):
                return False
            if expected[-1] and expected != [None] * 7 + [expected[-1]]:
                return False
            if not expected[-1] and (any(value is None for value in expected[:6]) or
                                    (expected[6] is None) != (backend == "aacgmv2")):
                return False
            comparison = _comparison(item["actual"], expected, bridges["tolerance"])
            invariants = item["invariants"]
            lat, lon, height = case["position"]
            orbit = OrbitResult(np.array([lat]), np.array([lon]), np.array([height]),
                                np.array([case["orbit_error"]]), "reference-WGS84-input")
            acquired = np.frombuffer(bytes.fromhex(item["actual_float64_little_endian_hex"]), dtype="<f8")
            result = MagneticResult(**{**{name: np.array([value]) for name, value in zip(FIELDS, acquired)},
                                       "backend": item["actual_backend"], "coordinate_system": item["actual_coordinate_system"]})
            observed_invariants = audit_magnetic_result(result, orbit)
            if not (comparison["passed"] and item["comparison"] == comparison and invariants["passed"] is True
                    and invariants == observed_invariants and item["actual_backend"] == backend
                    and invariants["backend"] == backend and all(value is True for value in invariants["checks"].values())):
                return False
        return True
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False
