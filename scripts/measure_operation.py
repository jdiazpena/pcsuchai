#!/usr/bin/env python3
"""Measure a complete command and retain its stdout/stderr without a new environment.

The command is passed after ``--`` and executed directly, never through a shell.
This wrapper adds observation/I/O work; use its labelled costs, not its enclosing
wall clock as a replacement for the scientific worker's primary latency.
"""

from __future__ import annotations

import argparse
import json
import os
import math
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__" and not sys.flags.no_user_site:
    os.execv(sys.executable, [sys.executable, "-s", *sys.argv])
sys.path.insert(0, str(ROOT / "src"))

from pcsuchai.campaign_costs import cost_clock
from pcsuchai.operation_costs import OperationCosts
from pcsuchai.retention import compress_retained_file
from pcsuchai.run_lock import serialized_run, inherited_lock_fds


def _children_cpu():
    """Return acquired waited-child CPU counters, or explicit unavailability."""

    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_CHILDREN)
        return {"status": "available", "user_seconds": value.ru_utime,
                "system_seconds": value.ru_stime, "source": "getrusage(RUSAGE_CHILDREN)",
                "scope": "waited_children_and_descendants_accounted_by_kernel_not_individual_worker"}
    except (ImportError, OSError) as exc:
        return {"status": "unavailable", "user_seconds": None, "system_seconds": None,
                "source": "getrusage(RUSAGE_CHILDREN)", "reason": str(exc)}


def _drain(stream, path, destination, errors, cancelled, abort):
    """Stream bounded chunks to raw files and optional terminal; never buffer history."""

    try:
        with stream, path.open("xb") as output:
            while not cancelled.is_set():
                ready, _, _ = select.select([stream.fileno()], [], [], 0.2)
                if not ready:
                    continue
                data = os.read(stream.fileno(), 64 * 1024)
                if not data:
                    break
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
                # A closed terminal must not discard the retained command log.
                if destination is not None:
                    try:
                        destination.buffer.write(data)
                        destination.buffer.flush()
                    except (BrokenPipeError, OSError):
                        destination = None
            output.flush()
            os.fsync(output.fileno())
    except BaseException as exc:
        errors.append(exc)
        abort()


def main():
    """Measure launch-through-exit, waited-child CPU and raw-output finalization."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-root", type=Path, default=ROOT / "outputs/operation-costs")
    parser.add_argument("--name", default="command")
    parser.add_argument("--quiet", action="store_true", help="retain raw logs without echoing them")
    parser.add_argument("--output-drain-timeout-seconds", type=float, default=30,
                        help="bound waiting for inherited pipes after command exit, not command runtime")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    if not math.isfinite(arguments.output_drain_timeout_seconds) or arguments.output_drain_timeout_seconds <= 0:
        parser.error("output-drain timeout must be finite and positive")
    return execute(arguments, command)


@serialized_run
def execute(arguments, command):
    """Hold the shared device lock through command/log completion and pass ownership."""

    costs = OperationCosts(arguments.receipt_root, arguments.name,
                           scope="external_command_setup_launch_exit_and_raw_log_finalization",
                           context={"command": command, "cwd": str(Path.cwd()),
                                    "detached_handoff_requested": "--detach" in command,
                                    "limit": "a detached command's exit is handoff, not campaign completion; wrapper interpreter/imports and lock acquisition before receipt setup are excluded"})
    print(f"COMMAND_RECEIPT: {costs.directory}", file=sys.stderr, flush=True)
    child = None
    handlers = {}
    forwarded = []
    errors = []
    drains = []
    cancelled = threading.Event()
    extra = {"launch_through_exit": None, "waited_children_cpu": None,
             "signals_forwarded": forwarded, "raw_logs": [],
             "raw_output_finalization_seconds": None}

    def forward(signum, frame):
        """Forward graceful stop to the owned command group, then wait/save its output."""

        forwarded.append({"signal": signum, "captured": cost_clock()})
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    def abort():
        """Request immediate graceful stop when raw observer persistence fails."""

        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    try:
        before_cpu = _children_cpu()
        environment = dict(os.environ)
        environment["PCSUCHAI_LAUNCH_OBSERVATION"] = json.dumps({"variant": "external_command_tee_v1",
            "attachment_scope": "current_command_until_exit", "chunk_bytes": 65536,
            "raw_log_sync": "each_acquired_chunk", "echo_to_terminal": not arguments.quiet}, sort_keys=True)
        launch = cost_clock()
        child = subprocess.Popen(command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, env=environment, pass_fds=inherited_lock_fds(environment))
        extra["child_pid"] = child.pid
        for name, stream, destination in (("stdout", child.stdout, sys.stdout), ("stderr", child.stderr, sys.stderr)):
            thread = threading.Thread(target=_drain, args=(stream, costs.directory / f"{name}.log",
                                      None if arguments.quiet else destination, errors, cancelled, abort), daemon=True)
            thread.start()
            drains.append(thread)
        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, forward)
        code = child.wait()
        exited = cost_clock()
        after_cpu = _children_cpu()
        extra["launch_through_exit"] = {"started": launch, "ended": exited,
                                         "wall_seconds": exited["monotonic_seconds"] - launch["monotonic_seconds"],
                                         "scope": "subprocess_Popen_to_wait_return_excluding_parent_log_finalization"}
        if before_cpu["status"] == after_cpu["status"] == "available":
            extra["waited_children_cpu"] = {"status": "available", "before": before_cpu, "after": after_cpu,
                "user_seconds": after_cpu["user_seconds"] - before_cpu["user_seconds"],
                "system_seconds": after_cpu["system_seconds"] - before_cpu["system_seconds"],
                "source": "getrusage(RUSAGE_CHILDREN)_cumulative_difference",
                "scope": after_cpu["scope"], "unit": "seconds"}
        else:
            extra["waited_children_cpu"] = {"status": "unavailable", "before": before_cpu,
                                            "after": after_cpu, "user_seconds": None, "system_seconds": None}
        # Descendants must close inherited output descriptors for EOF. Ordinary
        # master detached mode explicitly closes them; arbitrary daemon commands
        # are outside this wrapper's supported measurement contract.
        finalization = time.monotonic()
        drain_deadline = time.monotonic() + arguments.output_drain_timeout_seconds
        for thread in drains:
            thread.join(max(0., drain_deadline - time.monotonic()))
        if any(thread.is_alive() for thread in drains):
            cancelled.set()
            for thread in drains:
                thread.join(1)
            raise RuntimeError("command exited but inherited output pipes did not close before drain timeout; retained logs may be partial")
        if errors:
            raise RuntimeError(f"raw command log persistence failed: {errors!r}")
        for name in ("stdout", "stderr"):
            path = compress_retained_file(costs.directory / f"{name}.log", remove_original=True)
            extra["raw_logs"].append(path.name)
        extra["raw_output_finalization_seconds"] = time.monotonic() - finalization
        costs.finish(status="returned", outcome={"exit_code": code,
                     "completion_scope": "detached_handoff" if "--detach" in command else "command_exit"}, extra=extra)
        return code if code >= 0 else 128 - code
    except BaseException as exc:
        # Do not leave an owned command running after an observer failure.
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            child.wait()
        cancelled.set()
        for thread in drains:
            thread.join(1)
        for name in ("stdout", "stderr"):
            path = costs.directory / f"{name}.log"
            if path.is_file() and not path.with_name(path.name + ".gz").exists():
                try:
                    extra["raw_logs"].append(compress_retained_file(path, remove_original=True).name)
                except OSError as compression_error:
                    exc.add_note(f"retained raw log could not be compressed: {compression_error}")
        try:
            costs.finish(status="raised", error={"type": type(exc).__name__, "message": str(exc)}, extra=extra)
        except BaseException as receipt_error:
            exc.add_note(f"operation terminal could not be committed at {costs.directory}: {receipt_error}")
        raise
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
