# Campaign phase and total costs

Each new API segment (including resume) retains an append-only, fsynced
`segments/SEGMENT/costs.jsonl` and an exclusively written `segment-cost.json`.
These are separate from individual job/stage clocks and duration budgets.
Recorded phases include source/input/snapshot preparation, preflight, provenance,
full validation or certificate verification, complete block execution, saved
acceptance preparation/audit, final state commit and final storage observation.
Completed calls and raised/interrupted calls retain their exact start/end
UTC/monotonic/parent-CPU boundaries. A returned call does not imply scientific
acceptance: campaign/attempt validation status remains separate.

`block_execution` includes its setup, recovery, warmups, jobs, retention and
checkpoint work. It is a containing span: do not add it to included job/stage
durations or add the other phases again to segment total. Parent process CPU
includes its own threads, not child process CPU. Full validation invoked in the
parent is included in parent CPU; fresh scientific children are not.

The API segment total includes preparation, all phases, final state commit,
journal flushes and unclassified orchestration gaps. It excludes device-lock
acquisition, interpreter/shell/detached-launch startup, its own final receipt
write and offline reports/transfers. Summing active API segments excludes pauses
between resume segments and never subtracts UTC clocks across reboots or NTP
adjustments. The full command/transfer boundaries still need separate evidence;
this receipt is deliberately not labelled unrestricted deployment elapsed time.
The automatic master/report/transfer receipts and optional external command
clock now provide separate scopes in
[whole-operation-costs.md](whole-operation-costs.md), not an additive correction
to this containing API total. Detached launcher handoff and child bootstrap
limitations remain explicit.

Reporting audits original phase counts, non-overlapping monotonic boundaries and
wall/CPU deltas against the total. All raw phase lines are retained byte-exact
(base64 within `campaign-costs.jsonl.gz`), including corrupt/partial lines. Unknown
old costs are not zero. Missing/corrupt totals cannot supply campaign throughput.
Scheduled valid measured jobs supply the numerator; warmups, reference-validation
jobs, failures and scientifically excluded jobs do not become completions.

The final storage observation records target filesystem capacity after full
validation, acceptance and final-state work. Forecasts prefer this newer saved
observation over pre-validation per-job capacity. Its acquisition time remains
explicit: the small final capacity/total receipts and later activity can still
make it stale. Imported analysis-host allocation never supplies target capacity.

No guarantee of zero loss on sudden power failure is made. An abrupt interruption
may leave committed phase lines without a total; report them as partial. Failures
before an output segment can be created cannot produce this segment ledger. The
operator/launch error remains the evidence for those failures.
