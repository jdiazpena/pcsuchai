"""Persistent analysis worker: one process, fresh scientific computation per job."""

from __future__ import annotations

import contextlib
import json
import math
import os
import selectors
import subprocess
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from .run_lock import inherited_lock_fds, serialized_run


def _utc() -> str:
    """Identify protocol events in UTC while timing with a monotonic clock."""

    return datetime.now(timezone.utc).isoformat()


def _send(stream, value: dict) -> None:
    """Write exactly one complete JSON protocol line and flush it immediately."""

    stream.write(json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n")
    stream.flush()


def _record_publication_failure(directory: Path | None, request_id: str | None,
                                error: Exception, *, terminal_committed: bool) -> dict:
    """Keep publication failure separate from immutable computation results.

    No second send/retry is attempted. A persisted terminal is hash identified,
    not overwritten or upgraded to supervisor-confirmed completion. Readiness
    failures have no attempt directory and retain structured stderr instead.
    """

    from .benchmark import sha256_file
    from .benchmark_suite import _atomic_write_json
    terminal = directory / "worker-response.json" if directory is not None else None
    record = {"schema_version": 1, "kind": "worker_response_publication_error",
              "failure_class": "worker_response_delivery" if isinstance(error, OSError) else "worker_response_publication",
              "request_id": request_id, "pid": os.getpid(), "captured_utc": _utc(),
              "error_type": type(error).__name__, "error": str(error),
              "terminal_response_committed": terminal_committed,
              "terminal_response_path": str(terminal) if terminal_committed else None,
              "terminal_response_sha256": sha256_file(terminal) if terminal_committed else None,
              "publication_attempts": 1, "automatic_retry": False,
              "supervisor_confirmation": "unavailable; this incident does not establish a completed benchmark slot"}
    if directory is not None:
        incident = directory / "worker-delivery-error.json"
        if incident.exists() or incident.is_symlink():
            raise FileExistsError(f"worker publication incident already exists: {incident}")
        _atomic_write_json(incident, record)
    print(json.dumps(record, separators=(",", ":"), allow_nan=False), file=sys.stderr, flush=True)
    return record


def _request_options(request: dict) -> dict:
    """Validate an analysis request before opening any output file.

    Output directories are new per attempt. The worker cannot overwrite a
    previous attempt. Parameters call the same production ``run_analysis``;
    input tables, selected TLEs and magnetic model objects are recomputed.
    """

    required = {"request_id", "measurement_path", "tle_path", "eop_path", "output_dir", "orbit_backend", "magnetic_backend", "limit", "plot_config_path", "benchmark"}
    optional = {"selection_method", "observation_level", "stage_interval_seconds", "native_memory_interval_seconds"}
    if not isinstance(request, dict) or not required <= request.keys() or request.keys() - required - optional:
        raise ValueError("worker request must contain exactly the analysis protocol fields")
    if request.get("selection_method", "prefix") not in ("full", "prefix", "spread"):
        raise ValueError("selection_method must be full, prefix or spread")
    if request.get("selection_method") == "full" and request["limit"] is not None:
        raise ValueError("full selection requires limit=null")
    if request.get("observation_level", "normal") not in ("minimal", "normal", "detailed"):
        raise ValueError("invalid observation_level")
    for name in ("stage_interval_seconds", "native_memory_interval_seconds"):
        value = request.get(name, 0.05 if name == "stage_interval_seconds" else 10.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if not isinstance(request["request_id"], str) or not request["request_id"]:
        raise ValueError("request_id must be a nonempty string")
    if request["orbit_backend"] not in ("astropy", "skyfield") or request["magnetic_backend"] not in ("aacgmv2", "apexpy"):
        raise ValueError("worker requires a supported complete orbit/magnetic pair")
    if type(request["benchmark"]) is not bool:
        raise ValueError("benchmark must be a boolean")
    limit = request["limit"]
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be null or a positive integer")
    for key in ("measurement_path", "tle_path", "eop_path", "output_dir"):
        if not isinstance(request[key], str) or not request[key]:
            raise ValueError(f"{key} must be a path string")
    if request["plot_config_path"] is not None and not isinstance(request["plot_config_path"], str):
        raise ValueError("plot_config_path must be null or a path string")
    output = Path(request["output_dir"])
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"worker attempt output already exists: {output}")
    for path in (output.parent / "stdout.log", output.parent / "stderr.log", output.parent / "worker-response.json",
                 output.parent / "worker-delivery-error.json"):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"worker attempt record already exists: {path}")
    return {key: value for key, value in request.items() if key != "request_id"}


@serialized_run
def serve(input_stream=None, output_stream=None) -> int:
    """Process sequential jobs until EOF/stop, preserving per-attempt raw logs.

    Imports persist; loaded measurement/TLE/model objects do not. Every job
    invokes the production pipeline. Figure cleanup is recorded, and logs sync
    before the response is committed. A failed job returns an explicit failure;
    it is never converted into a retry or an apparent successful iteration.
    """

    input_stream = sys.stdin if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    started = time.monotonic()
    from .pipeline import run_analysis
    from .observations import process_measurements
    from .benchmark_suite import _atomic_write_json
    ready = {
        "kind": "ready", "pid": os.getpid(), "started_utc": _utc(),
        "imports_seconds": time.monotonic() - started,
        "reuse": {"imports": True, "measurement_arrays": False, "tle_objects": False, "magnetic_model_objects": False},
    }
    try:
        _send(output_stream, ready)
    except (OSError, ValueError) as exc:
        _record_publication_failure(None, None, exc, terminal_committed=False)
        return 2
    for line in input_stream:
        request = None
        log_dir = None
        terminal_committed = False
        fatal_protocol_failure = False
        try:
            request = json.loads(line)
            if request == {"kind": "stop"}:
                _send(output_stream, {"kind": "stopped", "pid": os.getpid(), "captured_utc": _utc()})
                return 0
            options = _request_options(request)
            log_dir = Path(options["output_dir"]).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            before = process_measurements(os.getpid(), scope="worker", native_memory=True)
            started_utc = _utc()
            with (log_dir / "stdout.log").open("x", encoding="utf-8") as stdout, (log_dir / "stderr.log").open("x", encoding="utf-8") as stderr:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    science_started = time.perf_counter()
                    try:
                        outputs = run_analysis(**options)
                        science_seconds = time.perf_counter() - science_started
                        response = {"status": "complete", "outputs": asdict(outputs)}
                    except Exception as exc:
                        science_seconds = time.perf_counter() - science_started
                        traceback.print_exc(file=stderr)
                        response = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
                    finally:
                        # Plotters normally close their own figures. Count any
                        # remaining live figures before the worker closes them;
                        # cleanup must not hide a recurring plotter resource leak.
                        figure_count = 0
                        if "matplotlib.pyplot" in sys.modules:
                            pyplot = sys.modules["matplotlib.pyplot"]
                            figure_count = len(pyplot.get_fignums())
                            pyplot.close("all")
                stdout.flush()
                stderr.flush()
                os.fsync(stdout.fileno())
                os.fsync(stderr.fileno())
            response.update({
                "kind": "result", "request_id": request["request_id"],
                "pid": os.getpid(), "started_utc": started_utc, "finished_utc": _utc(),
                "worker_science_seconds": science_seconds,
                "live_figures_before_cleanup": figure_count,
                "worker_resources_before": before,
                "worker_resources_after": process_measurements(os.getpid(), scope="worker", native_memory=True),
                "reuse": {"imports": True, "measurement_arrays": False, "tle_objects": False, "magnetic_model_objects": False},
            })
            _atomic_write_json(log_dir / "worker-response.json", response)
            terminal_committed = True
        except Exception as exc:
            # Malformed requests and persistence errors belong to the protocol
            # failure class. Existing output paths are never overwritten here.
            response = {"kind": "result", "status": "protocol_failed",
                        "request_id": request.get("request_id") if isinstance(request, dict) else None,
                        "pid": os.getpid(), "error_type": type(exc).__name__, "error": str(exc),
                        "captured_utc": _utc()}
            fatal_protocol_failure = log_dir is not None
        try:
            _send(output_stream, response)
        except (OSError, ValueError) as exc:
            _record_publication_failure(log_dir, request.get("request_id") if isinstance(request, dict) else None,
                                        exc, terminal_committed=terminal_committed)
            return 2
        if fatal_protocol_failure:
            return 2
    return 0


class PersistentWorkerError(RuntimeError):
    """A scientific/protocol failure with its complete worker response attached."""

    def __init__(self, response: dict) -> None:
        self.response = response
        super().__init__(f"persistent worker {response.get('status')}: {response.get('error_type')}: {response.get('error')}")


class PersistentWorker:
    """Supervise a sequential worker with bounded protocol buffers and timeouts.

    Scientific products/attempt logs are independent of the worker's lifetime
    stderr log. The manager preserves every protocol message in a durable JSONL
    journal. It never starts a replacement worker after an observation timeout.
    """

    def __init__(self, directory: Path, environment: dict[str, str], timeout_seconds: float = 7200) -> None:
        """Start one worker and wait for its readiness/import metadata."""

        from .benchmark_suite import _append_jsonl
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("worker timeout must be finite and positive")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.timeout_seconds = timeout_seconds
        self.buffer = b""
        self.pending = False
        self.closed = False
        self.stderr = (self.directory / "worker.stderr.log").open("xb")
        self.journal_path = self.directory / "protocol.jsonl"
        launch_started = time.monotonic()
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "pcsuchai.worker"], env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
                pass_fds=inherited_lock_fds(environment), start_new_session=True,
                bufsize=0,
            )
        except BaseException:
            self.stderr.close()
            raise
        self.selector = selectors.DefaultSelector()
        assert self.process.stdout is not None
        os.set_blocking(self.process.stdout.fileno(), False)
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            self.ready = self._receive(timeout_seconds)
            if self.ready.get("kind") != "ready" or self.ready.get("pid") != self.process.pid:
                raise RuntimeError("worker did not return its matching ready identity")
            self.ready["supervisor_startup_seconds"] = time.monotonic() - launch_started
            _append_jsonl(self.journal_path, {"event": "ready_observed", "response": self.ready, "captured_utc": _utc()})
        except BaseException:
            self.close(graceful=False)
            raise

    def _receive(self, timeout_seconds: float) -> dict:
        """Wait on the actual live descriptor; timeout never implies successful exit."""

        from .benchmark_suite import _append_jsonl
        deadline = time.monotonic() + timeout_seconds
        while True:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                response = json.loads(line)
                _append_jsonl(self.journal_path, {"event": "response", "response": response, "captured_utc": _utc()})
                return response
            if len(self.buffer) > 4 * 1024 * 1024:
                raise RuntimeError("worker protocol exceeded the declared response buffer limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"persistent worker response deadline exceeded; pid={self.process.pid}, returncode={self.process.poll()}")
            if not self.selector.select(remaining):
                continue
            block = os.read(self.process.stdout.fileno(), 65536)
            if not block:
                raise RuntimeError(f"persistent worker protocol closed; returncode={self.process.poll()}, stderr={self.directory / 'worker.stderr.log'}")
            self.buffer += block

    def execute(self, request: dict) -> tuple[dict, float, dict]:
        """Execute one scheduled request; report supervisor round-trip separately."""

        from .benchmark_suite import _append_jsonl
        if self.closed or self.pending:
            raise RuntimeError("worker closed or a previous request is still pending")
        _request_options(request)
        _append_jsonl(self.journal_path, {"event": "request", "request": request, "captured_utc": _utc()})
        started = time.perf_counter()
        self.pending = True
        self.process.stdin.write((json.dumps(request, allow_nan=False) + "\n").encode())
        self.process.stdin.flush()
        response = self._receive(self.timeout_seconds)
        elapsed = time.perf_counter() - started
        if response.get("request_id") != request["request_id"]:
            raise RuntimeError("worker response identity does not match the scheduled request")
        self.pending = False
        if response.get("status") != "complete":
            raise PersistentWorkerError(response)
        return response["outputs"], elapsed, response

    def close(self, *, graceful: bool = True) -> None:
        """Stop/close the actual worker handle, retaining protocol and stderr bytes.

        Idle close sends a stop request. A pending timed-out job is terminated
        and classified by its caller; it is not resumed as a successful attempt.
        These actions do not delete any recoverable scientific product or log.
        """

        if self.closed:
            return
        close_started = time.monotonic()
        try:
            if self.process.poll() is None:
                if graceful and not self.pending:
                    self.process.stdin.write(b'{"kind":"stop"}\n')
                    self.process.stdin.flush()
                    self._receive(min(self.timeout_seconds, 10))
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.selector.close()
            self.process.stdin.close()
            self.process.stdout.close()
            self.stderr.flush()
            os.fsync(self.stderr.fileno())
            self.stderr.close()
            self.closed = True
            from .benchmark_suite import _atomic_write_json
            _atomic_write_json(self.directory / "worker-exit.json", {
                "pid": self.process.pid, "return_code": self.process.poll(),
                "finished_utc": _utc(), "shutdown_seconds": time.monotonic() - close_started,
                "pending_request_at_close": self.pending,
                "graceful_requested": graceful,
            })

    def __enter__(self):
        """Use the supervisor as a resource-safe context manager."""

        return self

    def __exit__(self, exc_type, exc, tb):
        """Close the worker on every exit without suppressing the original error."""

        self.close(graceful=exc is None)


def request_from_analysis_command(command: list[str], request_id: str) -> dict:
    """Translate existing analysis CLI options into the identical worker call.

    Reject unhandled options, preventing a new analysis option from silently
    disappearing in persistent mode. Both paths keep the complete scientific
    pipeline and output selection; only interpreter lifetime differs.
    """

    marker = command.index("analyze")
    options = command[marker + 1:]
    mapping = {"--measurements": "measurement_path", "--tle": "tle_path", "--eop": "eop_path",
               "--output-dir": "output_dir", "--orbit-backend": "orbit_backend",
               "--magnetic-backend": "magnetic_backend", "--limit": "limit", "--plot-config": "plot_config_path",
               "--selection-method": "selection_method", "--observation-level": "observation_level",
               "--stage-interval-seconds": "stage_interval_seconds", "--native-memory-interval-seconds": "native_memory_interval_seconds"}
    request = {"request_id": request_id, "limit": None, "plot_config_path": None, "benchmark": False}
    while options:
        flag = options.pop(0)
        if flag == "--benchmark":
            request["benchmark"] = True
            continue
        if flag not in mapping or not options:
            raise ValueError(f"persistent worker cannot silently ignore analysis option {flag}")
        value = options.pop(0)
        request[mapping[flag]] = int(value) if flag == "--limit" else float(value) if flag in ("--stage-interval-seconds", "--native-memory-interval-seconds") else value
    return request


class AnalysisExecutor:
    """One resource-safe execution policy shared by all campaign phases."""

    def __init__(self, process_mode: str) -> None:
        """Select fresh or persistent lifetime without silently changing science."""

        if process_mode not in ("fresh", "persistent"):
            raise ValueError("process_mode must be fresh or persistent")
        self.process_mode = process_mode
        self.worker = None
        self.last_request = None
        self.last_response = None
        self.retained_streams: dict | None = None
        self.stream_retention_attempted = False
        self.campaign_resources = contextlib.ExitStack()

    def manage_cleanup(self, callback) -> None:
        """Own a campaign recorder's cleanup before it starts acquiring samples."""

        self.campaign_resources.callback(callback)

    def start(self, directory: Path, environment: dict[str, str], timeout_seconds: float) -> None:
        """Start persistent imports before recovery, retaining startup separately."""

        if self.process_mode == "persistent":
            self.worker = PersistentWorker(directory, environment, timeout_seconds)

    @property
    def metadata(self) -> dict:
        """Describe actual interpreter lifetime and startup/protocol provenance."""

        value = {"mode": self.process_mode, "input_object_reuse": False}
        if self.worker is not None:
            value.update({"pid": self.worker.process.pid, "ready": self.worker.ready,
                          "protocol_path": str(self.worker.journal_path) + ".gz",
                          "stderr_path": str(self.worker.directory / "worker.stderr.log") + ".gz",
                          "live_protocol_path": str(self.worker.journal_path) if not self.worker.closed else None,
                          "worker_exit_path": str(self.worker.directory / "worker-exit.json"),
                          "worker_command": [sys.executable, "-m", "pcsuchai.worker"],
                          "iteration_timer": "request send through response parsing and protocol journal sync"})
            if self.retained_streams is not None:
                value["stream_retention"] = self.retained_streams
        return value

    def run(self, command: list[str], timeout_seconds: float, environment: dict[str, str], *, fresh_runner):
        """Invoke the existing child runner or the same options in the live worker."""

        if self.process_mode == "fresh":
            return fresh_runner(command, timeout_seconds, environment)
        if self.worker is None:
            raise RuntimeError("persistent execution requires a started worker")
        directory = Path(command[command.index("--output-dir") + 1]).parent
        self.last_request = request_from_analysis_command(command, directory.name)
        self.last_response = None
        try:
            outputs, elapsed, self.last_response = self.worker.execute(self.last_request)
        except PersistentWorkerError as exc:
            self.last_response = exc.response
            raise
        return outputs, elapsed, ""

    def close(self) -> None:
        """Release recorders/processes once, without retrying failed log retention."""

        try:
            self.campaign_resources.close()
        finally:
            if self.worker is not None:
                self.worker.close()
                if self.retained_streams is None and not self.stream_retention_attempted:
                    self.stream_retention_attempted = True
                    from .retention import compress_retained_file
                    from .benchmark import sha256_file
                    started = time.monotonic()
                    files = []
                    for path in (self.worker.journal_path, self.worker.directory / "worker.stderr.log"):
                        compressed = compress_retained_file(path, remove_original=True)
                        files.append({"path": str(compressed), "sha256": sha256_file(compressed), "size_bytes": compressed.stat().st_size})
                    self.retained_streams = {"files": files, "retention_seconds": time.monotonic() - started}


def managed_analysis_execution(function):
    """Supply and finalize one executor for a complete public campaign call."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        if "_executor" in kwargs:
            raise ValueError("campaign execution resources are managed internally")
        # Process policy is a keyword-only addition in callers. Bind positional
        # arguments too so the Python API cannot accidentally use another mode.
        import inspect
        bound = inspect.signature(function).bind_partial(*args, **kwargs)
        if "_executor" in bound.arguments:
            raise ValueError("campaign execution resources are managed internally")
        executor = AnalysisExecutor(bound.arguments.get("process_mode", "fresh"))
        kwargs["_executor"] = executor
        try:
            return function(*args, **kwargs)
        finally:
            primary_error = sys.exception()
            try:
                executor.close()
            except BaseException as cleanup_error:
                if primary_error is None:
                    raise
                primary_error.add_note(f"campaign cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}")

    return wrapped


if __name__ == "__main__":
    raise SystemExit(serve())
