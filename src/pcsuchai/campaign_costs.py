"""Durable parent-side phase clocks outside scientific job duration budgets."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone


def cost_clock() -> dict:
    """Acquire UTC identity, monotonic wall and parent-process CPU clocks."""

    return {"captured_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_seconds": time.monotonic(), "process_cpu_seconds": time.process_time()}


class CampaignCosts:
    """Append/fsync every completed or failed phase; preserve partial journals.

    Parent CPU includes its threads, not child CPU. Phases are non-overlapping
    call spans; block_execution includes recovery/warmups/jobs/retention and must
    not be added to its job/stage sub-times. Total segment timing includes journal
    writes and unclassified orchestration gaps, but excludes its own final receipt
    write, lock acquisition, shell launch and offline reporting/export.
    """

    def __init__(self, directory, started: dict):
        self.directory = directory
        self.started = started
        self.handle = (directory / "costs.jsonl").open("x", encoding="utf-8")
        self.index = 0
        self.record("prepare_source_inputs_snapshots", started, cost_clock(), "complete")

    def record(self, name: str, started: dict, ended: dict, status: str, error_type=None) -> None:
        """Commit one phase with exact boundaries and explicit failure status."""

        self.index += 1
        row = {"schema_version": 1, "index": self.index, "phase": name,
               "started": started, "ended": ended,
               "wall_seconds": ended["monotonic_seconds"] - started["monotonic_seconds"],
               "parent_process_cpu_seconds": ended["process_cpu_seconds"] - started["process_cpu_seconds"],
               "status": status, "error_type": error_type,
               "scope": "master_parent_call_span", "source": "time.monotonic/time.process_time",
               "units": {"wall_seconds": "seconds", "parent_process_cpu_seconds": "seconds"}}
        self.handle.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    @contextmanager
    def phase(self, name: str):
        """Close and retain the attempted call even when it raises or interrupts."""

        started, status, error_type = cost_clock(), "complete", None
        try:
            yield
        except BaseException as exc:
            status, error_type = "failed", type(exc).__name__
            raise
        finally:
            self.record(name, started, cost_clock(), status, error_type)

    def call(self, name: str, function, *args, **kwargs):
        """Measure an existing function without changing its return/exception."""

        with self.phase(name):
            return function(*args, **kwargs)

    def finish(self, status: str) -> dict:
        """Close the raw journal and exclusively save the total segment receipt."""

        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        ended = cost_clock()
        result = {"schema_version": 1, "status": status, "started": self.started, "ended": ended,
                  "wall_seconds": ended["monotonic_seconds"] - self.started["monotonic_seconds"],
                  "parent_process_cpu_seconds": ended["process_cpu_seconds"] - self.started["process_cpu_seconds"],
                  "phase_records": self.index, "raw_journal": "costs.jsonl",
                  "scope": "master_API_segment_including_preparation_and_final_state_commit",
                  "source": "time.monotonic/time.process_time", "units": "seconds",
                  "limit": "excludes own receipt write, lock acquisition, shell/detached startup and later reporting/export; parent CPU excludes child CPU"}
        with (self.directory / "segment-cost.json").open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return result
