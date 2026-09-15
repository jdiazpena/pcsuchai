"""Safe session control using process identity and per-segment stop requests."""

from __future__ import annotations

import json
import os
import signal
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from pathlib import Path


def process_identity(pid: int | None = None) -> dict:
    """Identify a Linux process without assuming that an old PID is still ours."""

    pid = os.getpid() if pid is None else pid
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"pid": pid, "start_clock_ticks": int(fields[19]), "state": fields[0],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "status": "available"}
    except (OSError, ValueError, IndexError) as exc:
        return {"pid": pid, "status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def identity_is_live(identity: dict) -> bool:
    """Require matching boot/start identity and a non-zombie process state."""

    if identity.get("status") != "available":
        return False
    actual = process_identity(identity["pid"])
    return (actual.get("status") == "available" and actual.get("state") not in ("Z", "X")
            and all(actual.get(key) == identity.get(key) for key in ("pid", "boot_id", "start_clock_ticks")))


def session_attempt_counts(session: dict) -> dict:
    """Derive counts from committed execution slots, not a stale final summary.

    Warm-ups are separate. Failed/interrupted measured slots consume attempts;
    duration protocols have no fixed scheduled denominator. Duplicate slot
    identities are corruption, not extra successful work.
    """

    measured = [item for item in session.get("execution_order", []) if item.get("kind") == "measured"]
    slots = [(item.get("round"), item.get("scenario")) for item in measured]
    if len(slots) != len(set(slots)):
        raise ValueError("duplicate measured attempt slot in checkpoint")
    settings = session.get("settings", {})
    repeats = settings.get("repeats")
    scheduled = repeats * len(session.get("scenarios", {})) if settings.get("duration_seconds") is None and repeats is not None else None
    return {"scheduled": scheduled, "started": len(measured),
            "scientifically_valid": sum(item.get("status") == "complete" for item in measured),
            "failed": sum(item.get("status") == "failed" for item in measured),
            "interrupted": sum(item.get("status") == "interrupted" for item in measured),
            "skipped": max(0, scheduled - len(measured)) if scheduled is not None else None,
            "automatic_retries": 0}


def experiment_status(directory: str | Path) -> dict:
    """Read durable experiment state and independently check its live identity."""

    path = Path(directory).resolve()
    state = json.loads((path / "experiment-state.json").read_text())
    segment = (state.get("segments") or [{}])[-1]
    live = identity_is_live(segment.get("identity", {}))
    # A block can run for hours without rewriting the root state. Read its
    # atomic checkpoint to expose committed progress during that interval.
    from .experiment_runner import _counts
    counts = _counts(state, path)
    return {"directory": str(path), "status": state["status"], "live": live,
            "segment_id": segment.get("id"), "identity": segment.get("identity"),
            "counts": counts, "phase": state.get("phase"),
            "reason": state.get("reason"), "finished_utc": state.get("finished_utc")}


def request_experiment_stop(directory: str | Path) -> dict:
    """Ask this segment to finish its active job; never signal an unverified PID.

    A stop file is immutable and belongs to one segment. Resume starts another
    segment and cannot delete or silently reuse a previous stop request.
    """

    from .benchmark_suite import _atomic_write_json
    status = experiment_status(directory)
    if not status["live"] or status["status"] != "running":
        return {"requested": False, "reason": "no verified live running experiment", **status}
    path = Path(directory).resolve() / "segments" / status["segment_id"] / "stop-request.json"
    if not path.exists():
        _atomic_write_json(path, {"segment_id": status["segment_id"],
                                  "requested_utc": datetime.now(timezone.utc).isoformat(),
                                  "policy": "finish_active_job_then_stop"})
    return {"requested": True, "stop_request": str(path), **status}


@contextmanager
def graceful_signals(stop_event):
    """Turn SIGINT/SIGTERM into safe-boundary requests and restore old handlers."""

    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        for number in previous:
            signal.signal(number, lambda *_args: stop_event.set())
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def numerical_controls(thread_policy: str, affinity: list[int] | None):
    """Apply declared process/thread controls and restore the caller's settings.

    Children inherit process affinity and numerical-library environment values.
    This does not change CPU governors, firmware limits, caches or OS policy.
    Existing loaded pools are limited/restored in one-thread mode; new imports
    inherit the declared environment. Entry and post-import provenance record
    actual pool limits separately from environment values.
    """

    from .experiment import thread_environment
    previous = dict(os.environ)
    effective = thread_environment(thread_policy, previous)
    changed = {key for key, value in effective.items() if previous.get(key) != value}
    original_affinity = os.sched_getaffinity(0) if affinity is not None else None
    if affinity is not None and (not set(affinity) <= original_affinity):
        raise ValueError("requested CPU affinity is outside the process's allowed CPU set")
    try:
        for key in changed:
            os.environ[key] = effective[key]
        if affinity is not None:
            os.sched_setaffinity(0, affinity)
        thread_keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS",
                       "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
        with ExitStack() as stack:
            # Existing imported pools ignore later environment changes. Apply
            # the declared baseline to those pools too and restore on exit.
            if thread_policy == "one":
                from threadpoolctl import threadpool_limits
                stack.enter_context(threadpool_limits(limits=1))
            from .provenance import native_thread_state
            yield {"thread_policy": thread_policy, "thread_environment": {key: effective.get(key) for key in thread_keys},
                   "native_threads_at_entry": native_thread_state(),
                   "requested_affinity": affinity, "effective_affinity": sorted(os.sched_getaffinity(0))}
    finally:
        if original_affinity is not None:
            os.sched_setaffinity(0, original_affinity)
        # threadpoolctl's first import sets this OpenMP compatibility variable.
        # Restore its prior state too; do not leave the caller changed merely
        # because this was the first pool-control job in this process.
        for key in changed | {"KMP_DUPLICATE_LIB_OK"}:
            if key in previous:
                os.environ[key] = previous[key]
            else:
                os.environ.pop(key, None)
