"""Versioned experiment contracts and reproducible scheduling primitives."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from .thermal import ThermalPolicy


def _object(value: object, name: str, required: set[str], optional: set[str] | None = None) -> dict:
    """Reject unknown/missing contract fields instead of silently ignoring them."""

    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    missing = required - value.keys()
    unknown = value.keys() - required - (optional or set())
    if missing or unknown:
        raise ValueError(f"{name}: missing={sorted(missing)}, unknown={sorted(unknown)}")
    return value


def _positive(value: object, name: str, *, integer: bool = False, zero: bool = False) -> None:
    """Validate numeric protocol values, excluding bools, NaNs and infinities."""

    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise ValueError(f"{name} must be {'an integer' if integer else 'numeric'}")
    if not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


def _choice(value: object, choices: tuple[str, ...], name: str) -> None:
    """Validate a named variant before starting work or writing a session."""

    if value not in choices:
        raise ValueError(f"{name} must be one of {choices}")


@dataclass(frozen=True)
class ExperimentManifest:
    """An immutable serialized contract; every execution uses a decoded copy.

    Legacy campaign profiles remain supported separately. New experiments have
    explicit work, stopping, process, thermal, observation and retention policy.
    Unknown keys fail validation so an operator cannot request ignored behavior.
    Session identity/ordering are recorded by the launcher, never inferred from
    the number of adjacent repetitions.
    """

    canonical_json: str

    @property
    def data(self) -> dict:
        """Return an independent copy; callers cannot mutate the frozen contract."""

        return json.loads(self.canonical_json)

    @property
    def sha256(self) -> str:
        """Identify the complete effective contract, including all policies."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> ExperimentManifest:
        """Load JSON with exact schema validation and deterministic serialization."""

        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, value: dict) -> ExperimentManifest:
        """Freeze the complete version-1 experiment specification.

        Attempts are scheduled executions per pair, not desired successes.
        Duration applies to a scenario block and begins after its warm-ups and
        recovery; the active job finishes. Retries are disabled in version 1.
        Declared reuse is disabled: persistent jobs recompute the same pipeline.
        """

        root = _object(value, "experiment", {
            "experiment_schema_version", "name", "kind", "sessions", "workload",
            "execution", "thermal", "observation", "retention", "validation",
        }, {"system_notes"})
        if "system_notes" in root:
            notes = _object(root["system_notes"], "system_notes", set(), {"cooling", "storage", "supply", "other"})
            for key, note in notes.items():
                if note is not None and (not isinstance(note, str) or not note.strip() or len(note) > 4096):
                    raise ValueError(f"system_notes.{key} must be null or a nonempty string of at most 4096 characters")
        if type(root["experiment_schema_version"]) is not int or root["experiment_schema_version"] != 1:
            raise ValueError("unsupported experiment_schema_version")
        if not isinstance(root["name"], str) or not root["name"].strip():
            raise ValueError("experiment name must be a nonempty string")
        _choice(root["kind"], ("acceptance", "equal_work", "sustained", "persistent", "counters", "scaling", "overhead"), "kind")
        _positive(root["sessions"], "sessions", integer=True)
        work = _object(root["workload"], "workload", {"measurements", "tle", "eop", "pairs", "selection", "plot_profiles"})
        for key in ("measurements", "tle", "eop"):
            if not isinstance(work[key], str) or not work[key]:
                raise ValueError(f"workload.{key} must be a path string")
        pairs = work["pairs"]
        allowed_pairs = {f"{orbit}-{mag}" for orbit in ("astropy", "skyfield") for mag in ("aacgmv2", "apexpy")}
        if not isinstance(pairs, list) or not pairs or any(not isinstance(pair, str) or pair not in allowed_pairs for pair in pairs) or len(set(pairs)) != len(pairs):
            raise ValueError("workload.pairs must be unique supported backend pairs")
        selection = _object(work["selection"], "selection", {"method", "sizes"})
        _choice(selection["method"], ("full", "prefix", "spread"), "selection.method")
        sizes = selection["sizes"]
        if not isinstance(sizes, list) or not sizes:
            raise ValueError("selection.sizes must be a nonempty unique list")
        for size in sizes:
            if size is not None:
                _positive(size, "selection size", integer=True)
        if len(set(sizes)) != len(sizes):
            raise ValueError("selection.sizes must be unique")
        if selection["method"] == "full" and sizes != [None]:
            raise ValueError("full selection requires sizes=[null]")
        profiles = work["plot_profiles"]
        if not isinstance(profiles, list) or not profiles:
            raise ValueError("plot_profiles must be a nonempty list")
        names = []
        for profile in profiles:
            _object(profile, "plot profile", {"name", "config"})
            if not isinstance(profile["name"], str) or not profile["name"]:
                raise ValueError("plot profile requires a name")
            if profile["config"] is not None and (not isinstance(profile["config"], str) or not profile["config"]):
                raise ValueError("plot config must be a path or null for minimal maps")
            names.append(profile["name"])
        if len(set(names)) != len(names):
            raise ValueError("plot profile names must be unique")
        if root["kind"] != "scaling" and (len(sizes) != 1 or len(profiles) != 1):
            raise ValueError("multiple sizes/profiles require a scaling experiment")
        execution = _object(root["execution"], "execution", {
            "process_mode", "stop", "warmups", "seed", "ordering", "cache_state",
            "threads", "affinity", "timeout_seconds", "failure_policy", "max_consecutive_failures",
        })
        _choice(execution["process_mode"], ("fresh", "persistent"), "process_mode")
        if (root["kind"] == "persistent") != (execution["process_mode"] == "persistent"):
            raise ValueError("persistent kind and process mode must be selected together")
        stop = _object(execution["stop"], "stop", {"kind", "value"})
        _choice(stop["kind"], ("attempts_per_pair", "duration_per_pair_seconds"), "stop.kind")
        _positive(stop["value"], "stop.value", integer=stop["kind"] == "attempts_per_pair")
        if root["kind"] in ("equal_work", "acceptance", "counters", "scaling", "overhead") and stop["kind"] != "attempts_per_pair":
            raise ValueError("this experiment requires fixed attempts")
        _positive(execution["warmups"], "warmups", integer=True, zero=True)
        _positive(execution["seed"], "seed", integer=True, zero=True)
        _positive(execution["timeout_seconds"], "timeout_seconds")
        _positive(execution["max_consecutive_failures"], "max_consecutive_failures", integer=True)
        _choice(execution["ordering"], ("balanced", "scenario_blocks"), "ordering")
        if root["kind"] in ("sustained", "persistent", "counters") and execution["ordering"] != "scenario_blocks":
            raise ValueError("sustained/persistent/counter work requires scenario blocks")
        _choice(execution["cache_state"], ("warmed_os_cache",), "cache_state")
        _choice(execution["threads"], ("one", "stock"), "threads")
        _choice(execution["failure_policy"], ("stop", "continue"), "failure_policy")
        affinity = execution["affinity"]
        if affinity is not None:
            if not isinstance(affinity, list) or not affinity:
                raise ValueError("affinity must be null or unique CPU indices")
            for cpu in affinity:
                _positive(cpu, "affinity CPU", integer=True, zero=True)
            if len(set(affinity)) != len(affinity):
                raise ValueError("affinity CPU indices must be unique")
        thermal = _object(root["thermal"], "thermal", {"mode", "policy", "maximum_temperature_c", "threshold_action"}, {"require_temperature_sensor"})
        if type(thermal.get("require_temperature_sensor", False)) is not bool:
            raise ValueError("require_temperature_sensor must be boolean")
        _choice(thermal["mode"], ("stable_each_attempt", "stable_before_block", "uncontrolled"), "thermal.mode")
        _choice(thermal["threshold_action"], ("stop",), "threshold_action")
        if thermal["maximum_temperature_c"] is not None:
            _positive(thermal["maximum_temperature_c"], "maximum_temperature_c")
        if thermal["mode"] == "uncontrolled":
            if thermal["policy"] is not None:
                raise ValueError("uncontrolled thermal mode requires policy=null")
        else:
            policy = _object(thermal["policy"], "thermal.policy", set(ThermalPolicy.__dataclass_fields__))
            ThermalPolicy(**policy)
        if root["kind"] == "equal_work" and thermal["mode"] != "stable_each_attempt":
            raise ValueError("equal-work baseline requires recovery before each attempt")
        if root["kind"] in ("sustained", "persistent") and thermal["mode"] == "stable_each_attempt":
            raise ValueError("sustained/persistent blocks cannot recover between jobs")
        observation = _object(root["observation"], "observation", {"levels", "stage_interval_seconds", "board_interval_seconds", "native_memory_interval_seconds", "counter_groups", "minimum_counter_coverage_percent"})
        levels = observation["levels"]
        if not isinstance(levels, list) or not levels or any(level not in ("minimal", "normal", "detailed") for level in levels) or len(set(levels)) != len(levels):
            raise ValueError("observation levels must be unique supported levels")
        if root["kind"] == "overhead" and not {"minimal", "normal"} <= set(levels):
            raise ValueError("overhead experiment requires matched minimal and normal jobs")
        if root["kind"] != "overhead" and len(levels) != 1:
            raise ValueError("multiple observation levels require an overhead experiment")
        for name in ("stage_interval_seconds", "board_interval_seconds", "native_memory_interval_seconds"):
            _positive(observation[name], name)
        _positive(observation["minimum_counter_coverage_percent"], "counter coverage")
        if observation["minimum_counter_coverage_percent"] > 100:
            raise ValueError("counter coverage cannot exceed 100 percent")
        groups = observation["counter_groups"]
        if not isinstance(groups, list):
            raise ValueError("counter_groups must be a list")
        for group in groups:
            if not isinstance(group, list) or not group or any(not isinstance(event, str) or not event or event.startswith("-") or "," in event for event in group):
                raise ValueError("counter groups require individual perf event names")
            scopes = {event.rsplit(":", 1)[-1] if ":" in event else "user_and_kernel" for event in group}
            if len(scopes) != 1:
                raise ValueError("counter events in a matched group require the same scope")
        if (root["kind"] == "counters") != bool(groups):
            raise ValueError("counter groups require a dedicated counters experiment")
        retention = _object(root["retention"], "retention", {"mode", "compression", "minimum_free_bytes", "flush_interval_seconds"})
        _choice(retention["mode"], ("all_raw_immutable",), "retention.mode")
        _choice(retention["compression"], ("verified_gzip_and_npz",), "retention.compression")
        _positive(retention["minimum_free_bytes"], "minimum_free_bytes", integer=True, zero=True)
        _positive(retention["flush_interval_seconds"], "flush_interval_seconds")
        if retention["flush_interval_seconds"] != 1:
            raise ValueError("version 1 supports a one-second raw stage fsync boundary")
        validation = _object(root["validation"], "validation", {"require_full_certificate", "allow_version_drift"})
        if any(type(item) is not bool for item in validation.values()):
            raise ValueError("validation options must be booleans")
        if validation["require_full_certificate"] and validation["allow_version_drift"]:
            raise ValueError("certified experiments cannot allow version drift")
        return cls(json.dumps(root, sort_keys=True, separators=(",", ":"), allow_nan=False))


def balanced_order(pairs: list[str], session_index: int, round_index: int, seed: int) -> list[str]:
    """Rotate a seeded base order so pairs occupy each position once per cycle.

    Indices are one-based. Independent sessions rotate positions too. Unlike
    independently shuffled rounds, a complete N-round cycle has exact position
    balance. Warm-ups must use separate identities from measured rounds.
    """

    if session_index < 1 or round_index < 1 or not pairs or len(set(pairs)) != len(pairs):
        raise ValueError("balanced schedule requires positive indices and unique pairs")
    base = list(pairs)
    random.Random(seed).shuffle(base)
    shift = (session_index + round_index - 2) % len(base)
    return base[shift:] + base[:shift]


def thread_environment(policy: str, original: dict[str, str]) -> dict[str, str]:
    """Apply declared numerical-library limits before importing native libraries."""

    _choice(policy, ("one", "stock"), "threads")
    environment = dict(original)
    if policy == "one":
        for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
            environment[name] = "1"
    return environment
