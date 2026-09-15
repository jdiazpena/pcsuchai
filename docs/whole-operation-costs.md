# Whole-operation cost accounting

Scientific job/stage timers remain the primary algorithm measurements. Startup,
recovery, acceptance, finalization and transfer are real additional operations,
not silently omitted deployment costs or values to add twice to a containing
clock. Use the existing installed Python; none of these commands installs
libraries, creates an environment or changes the OS.

## Saved scopes

| Receipt/metric | Actual measured span | Important exclusion or limit |
|---|---|---|
| Master run/resume | After stdlib bootstrap, before project imports, through result printing | Interpreter/stdlib/`-s` re-exec startup and terminal receipt write excluded |
| API report/export/import | Complete locked public call, including receipt setup and all function work | Lock acquisition, earlier imports and terminal receipt write excluded |
| External launch-through-exit | Before `Popen` through its `wait` return | Parent output drain/compression excluded; this includes command interpreter/imports |
| External whole operation | Wrapper receipt setup, command execution, output drain/fsync/compression | Wrapper interpreter/imports/lock acquisition before setup and own terminal receipt write excluded |
| Campaign API segment | Preparation through final state/capacity work | Contained in master/external spans; see [campaign-costs.md](campaign-costs.md) |
| Recovery acquisition | Gate/baseline through raw compression/hash | Contained in block/API spans; see [thermal-stress.md](thermal-stress.md) |

Master receipts are automatic for `run` and `resume`, including the detached
launcher and its actual child. They are under
`EXPERIMENT_PARENT/operation-costs/YYYY/MM/DD/UTC-master-OPERATION-UNIQUE/`.
The master prints `MASTER_COST_RECEIPT:` on stderr; normal result stdout is
unchanged. Report/export/import receipts are automatic API/CLI output-producing
calls under `OUTPUT_PARENT/operation-costs/YYYY/MM/DD/UTC-OPERATION-UNIQUE/`.
Each call retains exclusive `intent.json` and `terminal.json` metadata. Small
metadata remains readable JSON; raw scientific arrays, timelines and logs remain
losslessly compressed. Existing payloads/archives/receipts are never replaced.

A returned API can contain a partial report, failed byte verification or stopped
campaign: `returned` does not mean scientifically accepted. A raised call saves
its actual costs/error even if no output was created. If receipt finalization
fails, intent/output survive and cost is unavailable; do not silently rerun a
completed operation. An abrupt process exit may leave only intent, never a
synthetic successful terminal. File fsync is implemented; sudden-power-loss
zero-loss guarantees are not made.

## Include interpreter startup and retain command output

For an externally observed foreground operation, prefix the existing command:

```bash
python3 scripts/measure_operation.py --name acceptance -- python3 scripts/run_experiment.py run --manifest configs/experiments/acceptance.json --device-label pi5
```

The wrapper prints `COMMAND_RECEIPT:`. Its default receipt root is
`outputs/operation-costs/`; `--receipt-root PATH` chooses another new-record
root. `--quiet` keeps full raw logs without echoing them. Commands are executed
directly after `--`, not interpolated through a shell. Both stdout/stderr are
streamed in bounded chunks, flushed/fsynced at acquisition and losslessly gzip
compressed after exit. Compression and output drain have their own measured
finalization time inside the external containing operation.

The wrapper forwards SIGINT/SIGTERM to its owned command group, waits for the
command to complete and holds/passes the same device lock through logging work.
It refuses a competing launch before creating observer files. The wrapper is
for complete processing/report/transfer commands, not for wrapping status/stop
queries while another job owns the lock. It waits for the
command's graceful stop and saves its output. The master still finishes/saves
the active scientific job. `--output-drain-timeout-seconds` (default 30) bounds
waiting for inherited output pipes **after exit**, not command execution time.
Commands that leave arbitrary daemons holding those pipes are not supported;
a drain timeout retains partial logs and an explicit observer failure, not a
clean completion. A command exiting nonzero has a recorded exit code; a spawn
failure has unavailable child timing/CPU, not zero.

This extra observer consumes CPU and storage I/O. The command receives an
opaque `PCSUCHAI_LAUNCH_OBSERVATION` process marker describing tee/sync/echo
policy. Runtime/control records preserve it, so wrapped/unwrapped settings stay
in separate scientific comparison cohorts. For a master `--detach`, the child
inherits a distinct upstream-launcher-only declaration: it is not claimed to
have an active stdout tee for its long-running jobs. This is a declared/inherited
context, not proof of a live external observer. Measure its overhead with matched
jobs; do not subtract an assumed constant or mix variants.

Wrapping a command containing `--detach` measures its **handoff**, not the
remaining campaign. The detached child's automatic master/segment receipts
are written when it stops/completes and survive closing SSH. They exclude the
child interpreter/stdlib bootstrap at their explicitly narrower boundary.
Their overlapping launcher/child spans cannot be added as total deployment
elapsed time. For a full interpreter-through-exit measurement use the external
foreground command; detached bootstrapping has only these declared scopes.

External child user/system CPU is the acquired difference of
`getrusage(RUSAGE_CHILDREN)` before/after waiting. It covers waited children and
kernel-accounted descendants, **not** an individual scientific worker or a
detached process still alive. Wrapper parent process CPU includes its output
threads, not child CPU. Missing support remains unavailable. These scopes follow
[Python resource documentation](https://docs.python.org/3/library/resource.html)
and [Linux getrusage documentation](https://man7.org/linux/man-pages/man2/getrusage.2.html).

## Audit saved costs without rerunning science

Pass each actual receipt root (or individual receipt directory) and a new output:

```bash
python3 scripts/run_experiment.py costs outputs/operation-costs --output outputs/reports/operation-costs-first
```

Multiple roots are accepted. Overlapping paths are inventoried once; copied
operation identities are marked invalid rather than counted twice. The audit
verifies schema/identity/units/source/scope, wall/CPU deltas and external
launch/exit/child-CPU/finalization subclocks. It preserves both original metadata
documents byte-exact, including malformed JSON, in `operation-costs.jsonl.gz`.
`operation-cost-report.json` contains each audited returned/raised call and all
returned/raised/unfinished/invalid counts. Missing terminals/corruption remain
explicit and do not supply timing-table values. No containing clocks are summed
into a guessed deployment time or hardware speedup. Recorded paths/recorder
runtime are not a complete frozen scientific work signature: scientific
comparisons still require the archived source/input/runtime/control evidence.

Cost receipts live outside immutable science/import/report payloads. Export
still includes every original experiment byte but cannot include its own later
export cost/digest. Retain/transfer the relevant `operation-costs/` directories
alongside the science bundle if these operating costs are needed on the analysis
PC. Import/report costs describe the machine where those operations ran, not
Pi target allocation or satellite transmission. No link rate, power meter,
external sensor or hardware measurement is invented.

`configs/verification/local-operation-functional.json` is a one-pair, 100-row
LOCAL functional test of these operator paths. Its uncontrolled thermal policy
and absent full certificate are explicit. It is not the required all-four-pair
Pi acceptance or a comparative hardware benchmark.
