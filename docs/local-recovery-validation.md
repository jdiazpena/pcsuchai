# Local abrupt-stop and recovery validation

This development check executes real native scientific jobs on the local PC.
It is not a Pi performance experiment, target acceptance, a thermal test or a
power-failure guarantee. Run it directly from the repository root, using the
existing Python with the required scientific libraries:

```bash
python3 scripts/verify_local_recovery.py --mode both
```

No dependency installation occurs. Do not run it inside `measure_operation.py`
or another wrapper that supplies an inherited benchmark-lock token: the check
requires each real master to acquire its normal device-wide lock. Do not run
other benchmark/validation/transfer jobs concurrently on this PC.

Every invocation creates separate, exclusive UTC-dated directories beneath
`outputs/verification/abrupt-recovery-workflow/YYYY/MM/DD/`. `--mode fixed` or
`--mode timed` selects one check; `--output-root PATH` changes the evidence root.
It never replaces a previous directory or retries a failed check automatically.

## Actual fault boundary

The driver launches the normal experiment master with a persistent worker,
Skyfield/ApexPy, 100 spread-selected input rows and all 32 archived plot recipes.
Each job still executes measurement loading, TLE selection, orbit propagation,
magnetic coordinates, geographic footpoints, filtering and saved maps/tables.
The local manifest is explicitly uncontrolled: it does not invent a Pi sensor
value. Its full-reference certificate requirement is disabled solely for this
orchestration diagnostic; this check does not certify the complete input or
replace full-data scientific acceptance.

Before injecting SIGKILL, the driver requires a durable attempt intent and
actual production CSV output, with no completed worker or supervisor record.
The worker must have a matching live boot/start identity and an actual Linux
parent PID equal to the exact supervisor handle launched by this driver. A
heartbeat or a saved PID alone is not sufficient signal authority.

Only that owned supervisor is abruptly killed. The native worker is allowed to
finish its active computation and exit after the closed response pipe. Its
completed `worker-response.json` remains unchanged. The separate
`worker-delivery-error.json` identifies the delivery failure and the committed
terminal's SHA-256; the worker does not attempt a second response send.
Readiness delivery failures have no fabricated attempt terminal and are
recorded on stderr instead.

The driver hashes every original orphan file after the worker exits, resumes
the normal master and verifies that every original byte is unchanged. New
reconciliation evidence is permitted; overwriting the original evidence is not.
Even when the worker's scientific result is complete, an unconfirmed supervisor
slot remains interrupted, with unavailable uncommitted timing. No elapsed time
or successful benchmark completion is inferred from the preserved result.

## Expected accounting

| Check | Required result |
|---|---|
| Fixed work | Four scheduled/started attempts; three product-validated completions and one interrupted attempt; zero automatic retries; protocol completes with exit 0 |
| Timed work | One started/interrupted attempt and no product-validated completion; remaining duration is explicitly unavailable after abrupt interruption; resume stops with exit 2 and launches no additional work |
| Saved report | Both campaigns remain `partial_or_excluded`; the interrupted attempt is retained rather than hidden in latency statistics |

“Protocol completes” does not mean all four fixed-work scientific attempts
succeeded. These short diagnostics have no full-reference-accepted attempts.

On success, `result.json` retains counts, real exit codes, reconciliation,
original file count and the saved-report result. Raw native arrays, selected
plot arrays, images, source/input snapshots, protocols and partial journals are
retained. The driver's four subprocess logs are losslessly gzip-compressed;
plain small metadata receipts remain readable. No benchmark evidence is pruned.

On failure, `failure.json` records the actual exception and observed exit codes;
an unavailable exit code remains null. Original logs and partial files remain.
Cleanup tracks both the original and resumed owned supervisor handles and any
verified native workers. It never uses broad process-name/group matching.
Observation timeout triggers explicit owned-process cleanup, not a relaunch or
an invented successful exit. A cleanup error is attached to the original fault
instead of replacing it.

This verifies software handling of the specified supervisor SIGKILL boundary.
It does not simulate loss of electricity, guarantee filesystem durability after
power failure, measure long-running resource stability, or establish behavior
on a Pi that has not produced its own acceptance evidence.
