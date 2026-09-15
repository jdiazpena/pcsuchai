"""Uncertainty from independent saved sessions, not independent hot-loop jobs.

Session resampling preserves every attempt and its within-session correlation.
Intervals describe the declared sessions, not an isolated silicon ranking or a
guarantee that three sessions are sufficient. No assumed overhead is subtracted.
"""

from __future__ import annotations

import numpy as np


def _clusters(values: dict[str, list[float]]) -> dict[str, np.ndarray]:
    """Validate positive durations, retaining unequal cluster sizes explicitly."""

    result = {}
    for identity, observations in sorted(values.items()):
        original = np.asarray(observations)
        if not isinstance(identity, str) or not identity or original.dtype.kind not in "ifu":
            raise ValueError("nonempty session IDs and numeric non-boolean durations are required")
        array = np.asarray(observations, dtype=float)
        if array.ndim != 1 or not np.all(np.isfinite(array)) or np.any(array <= 0):
            raise ValueError("session durations must be finite, positive vectors")
        if array.size:
            result[identity] = array
    return result


def session_statistics(values: dict[str, list[float]], *, seed: int = 1729,
                       resamples: int = 2000, confidence: float = 0.95) -> dict:
    """Summarize attempts and bootstrap whole sessions with a frozen seed.

    The primary statistic is the median of session medians (equal session
    weight). Attempt median/p95 are descriptive; their intervals resample whole
    sessions, including their original sizes, without resampling adjacent jobs.
    A single observed session has no identifiable between-session uncertainty.
    """

    if type(seed) is not int or type(resamples) is not int or resamples < 100:
        raise ValueError("integer seed and at least 100 resamples are required")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    clusters = _clusters(values)
    arrays = list(clusters.values())
    pooled = np.concatenate(arrays) if arrays else np.array([], dtype=float)
    medians = np.array([np.median(array) for array in arrays])
    result = {
        "unit": "seconds", "attempt_count": int(pooled.size), "session_count": len(arrays),
        "session_attempt_counts": {key: len(array) for key, array in clusters.items()},
        "session_medians": {key: float(np.median(array)) for key, array in clusters.items()},
        "primary_estimator": "median_of_session_medians_equal_session_weight",
        "median_of_session_medians": float(np.median(medians)) if medians.size else None,
        "attempt_median": float(np.median(pooled)) if pooled.size else None,
        "attempt_p95": float(np.quantile(pooled, 0.95)) if pooled.size else None,
        "attempt_minimum": float(np.min(pooled)) if pooled.size else None,
        "attempt_maximum": float(np.max(pooled)) if pooled.size else None,
        "attempt_iqr": float(np.quantile(pooled, 0.75) - np.quantile(pooled, 0.25)) if pooled.size else None,
        "uncertainty": {"method": "percentile_whole_session_cluster_bootstrap_no_within_session_resampling",
                        "seed": seed, "resamples": resamples, "confidence": confidence,
                        "status": "available" if len(arrays) >= 2 else "unavailable",
                        "reason": None if len(arrays) >= 2 else "fewer than two observed independent sessions",
                        "small_session_sample": len(arrays) < 5,
                        "p95_limit": "empirical tail quantile; small attempt/session counts do not establish tail precision",
                        "intervals": {}},
    }
    if len(arrays) >= 2:
        rng = np.random.default_rng(seed)
        draws = {name: [] for name in ("median_of_session_medians", "attempt_median", "attempt_p95")}
        for _ in range(resamples):
            indices = rng.integers(0, len(arrays), size=len(arrays))
            chosen = np.concatenate([arrays[index] for index in indices])
            draws["median_of_session_medians"].append(float(np.median(medians[indices])))
            draws["attempt_median"].append(float(np.median(chosen)))
            draws["attempt_p95"].append(float(np.quantile(chosen, 0.95)))
        alpha = (1 - confidence) / 2
        result["uncertainty"]["intervals"] = {
            name: [float(value) for value in np.quantile(draw, [alpha, 1 - alpha])]
            for name, draw in draws.items()
        }
    return result


def session_ratio(reference: dict[str, list[float]], candidate: dict[str, list[float]], *,
                  paired: bool = False, seed: int = 1729, resamples: int = 2000,
                  confidence: float = 0.95) -> dict:
    """Bootstrap a latency ratio; paired variants require exact session identity.

    Reference/candidate > 1 means the candidate is faster. Paired observation
    levels on the same board use median per-session ratios; separate boards use
    independent resampling of their session medians. This function cannot prove
    workload comparability or scientific acceptance; the report must do so first.
    """

    first, second = _clusters(reference), _clusters(candidate)
    if not first or not second:
        return {"status": "unavailable", "reason": "no valid durations in one cohort", "ratio": None}
    if paired and first.keys() != second.keys():
        return {"status": "unavailable", "reason": "paired variants require the same complete session identities", "ratio": None}
    # Share validation and the explicit interval contract with latency summaries.
    session_statistics(first, seed=seed, resamples=resamples, confidence=confidence)
    session_statistics(second, seed=seed, resamples=resamples, confidence=confidence)
    a = np.array([np.median(array) for array in first.values()])
    b = np.array([np.median(array) for array in second.values()])
    ratio = float(np.median(a / b)) if paired else float(np.median(a) / np.median(b))
    result = {"status": "available", "ratio": ratio,
              "definition": "reference_latency/candidate_latency; >1 means candidate faster",
              "estimator": "median_of_paired_session_ratios" if paired else "ratio_of_medians_of_session_medians",
              "paired": paired, "reference_session_count": len(a), "candidate_session_count": len(b),
              "uncertainty": {"status": "available" if min(len(a), len(b)) >= 2 else "unavailable",
                              "method": "paired_session_bootstrap" if paired else "independent_session_bootstrap",
                              "seed": seed, "resamples": resamples, "confidence": confidence,
                              "small_session_sample": min(len(a), len(b)) < 5,
                              "interval": None, "reason": None if min(len(a), len(b)) >= 2 else "fewer than two sessions in one cohort"}}
    if min(len(a), len(b)) >= 2:
        rng = np.random.default_rng(seed)
        draws = []
        for _ in range(resamples):
            ai = rng.integers(0, len(a), size=len(a))
            bi = ai if paired else rng.integers(0, len(b), size=len(b))
            draws.append(float(np.median(a[ai] / b[bi])) if paired else float(np.median(a[ai]) / np.median(b[bi])))
        alpha = (1 - confidence) / 2
        result["uncertainty"]["interval"] = [float(value) for value in np.quantile(draws, [alpha, 1 - alpha])]
    return result
