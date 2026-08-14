"""Project-specific exceptions with actionable user-facing messages."""


class PCSException(Exception):
    """Base exception for expected PCS SUCHAI processing failures."""


class DataValidationError(PCSException):
    """Raised when an input file violates the documented data contract."""


class BackendUnavailableError(PCSException):
    """Raised when a selected optional processing backend is not installed."""
