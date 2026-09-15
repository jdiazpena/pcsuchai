"""Project-specific exceptions with actionable user-facing messages."""


class PCSException(Exception):
    """Base exception for expected PCS SUCHAI processing failures."""


class DataValidationError(PCSException):
    """Raised when an input file violates the documented data contract."""


class BackendUnavailableError(PCSException):
    """Raised when a selected optional processing backend is not installed."""


class ScientificValidationError(RuntimeError, PCSException):
    """A completed computation failed the saved scientific/product contract."""


class WorkerExecutionError(RuntimeError, PCSException):
    """A launched worker exited unsuccessfully; its logs retain the cause."""


class WorkerProtocolError(RuntimeError, PCSException):
    """A worker response did not conform to the expected result protocol."""


def failure_classification(exc: Exception) -> str:
    """Distinguish known failures without guessing causes from message text.

    Unsupported observations are not exceptions here: their availability schema
    remains separate. Unknown exceptions are explicitly unresolved, rather than
    being relabelled scientific failures or missing telemetry.
    """

    import errno
    import subprocess

    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return "disk_exhaustion"
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "worker_timeout"
    if isinstance(exc, ScientificValidationError):
        return "scientific_validation"
    if isinstance(exc, DataValidationError):
        return "input_validation"
    if isinstance(exc, BackendUnavailableError):
        return "selected_backend_unavailable"
    if isinstance(exc, WorkerProtocolError):
        return "worker_protocol"
    if isinstance(exc, WorkerExecutionError):
        return "worker_execution_see_retained_logs"
    return "unresolved_orchestration_or_computation"
