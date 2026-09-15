import errno
import subprocess

import pytest

from pcsuchai.errors import ScientificValidationError, WorkerExecutionError, WorkerProtocolError, failure_classification
from pcsuchai.benchmark_suite import _validate_run


@pytest.mark.parametrize("failure,category", [
    (OSError(errno.ENOSPC, "test disk full"), "disk_exhaustion"),
    (subprocess.TimeoutExpired(["test"], 1), "worker_timeout"),
    (ScientificValidationError("invalid plot"), "scientific_validation"),
    (WorkerExecutionError("native exit"), "worker_execution_see_retained_logs"),
    (WorkerProtocolError("malformed response"), "worker_protocol"),
    (RuntimeError("unknown"), "unresolved_orchestration_or_computation"),
])
def test_distinct_failures_are_not_missing_metrics(failure, category):
    assert failure_classification(failure) == category


def test_missing_completed_product_is_scientific_failure():
    with pytest.raises(ScientificValidationError):
        _validate_run({}, 1)
