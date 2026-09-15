# Saved I/O and hardware-counter reports

The existing `report` command adds `resource_analysis` to
`experiment-report.json`. It reads archived data only: no scientific model or
`perf` command is executed, and the original experiments remain unchanged.

## Stage resource tables

Each table identifies the controlled cohort, board label, backend pair,
warmup/measured phase, outcome, stage, metric, unit and source. It reports
read/write bytes, read/write characters, voluntary/involuntary context switches
and minor/major page faults from verified stage endpoint records. Genuine zero
is available; missing, boolean, negative and non-finite values are not zero.
`stage_attempts` identifies attempts with no saved stage records, including
minimal instrumentation or failures before stage products were committed.

Observed summaries keep every available value, including failed/excluded and
warmup observations in their separate outcome tables. `accepted_measured`
includes only complete, scientifically checked, controlled measured attempts.
Session counts are explicit. Integer totals remain exact; `median_exact` is a
rational numerator/denominator pair, so counts above 2^53 are not rounded.
These are descriptive counts, not independent-hot-loop confidence intervals.

On Linux, read/write bytes describe storage-layer accounting; read/write
characters describe logical syscall transfers, which may be satisfied by
caches. Process I/O can include waited-for children. These are not downlink
bytes, SD-card wear or electrical measurements.
[Linux process I/O documentation](https://man7.org/linux/man-pages/man5/proc_pid_io.5.html).
Stage deltas do not include later parent compression/sharing. Board/supervisor
sampled cumulative counters remain separate in `observations.jsonl.gz` and
`reading_trends`; no endpoint delta is invented from incomplete samples.

## Repeated hardware counters

Each scheduled counter attempt is re-read from its own retained
`perf-stat.csv.gz` (or an interrupted plain CSV). Numbers in `run-record.json`
are metadata, not numerical evidence. The reader uses the archived simultaneous
event group and minimum coverage policy. It requires exactly the requested
events, without duplicate/unparsed substitute events, before accepting a group.
This also fixes the live group reader's former count-only acceptance check.

`hardware-counters.jsonl.gz` preserves each attempt's source text bytes as
base64, SHA-256, original recorded metadata, reparsed event values, scopes,
units, availability, running time, coverage and quality. Malformed UTF-8 and
unparsed lines remain recoverable byte-for-byte. Corrupt compressed containers
remain in the original immutable campaign and are listed as invalid evidence;
they cannot provide decoded numerical measurements. Linked counter paths are
refused without reading external bytes.

Counter tables retain unsupported/not-counted events and missing requested
event slots. Denied/missing collection supplies unavailable slots, not zeros.
Poor-coverage observations remain visible but are excluded from accepted-value
summaries. Failed/excluded/warmup counts never become accepted measured counts.
Reported integer event counts remain exact. Coverage-rounded enabled time and
scaled values are explicitly estimates, not exact kernel accounting. IPC is
available only with one cycles/instructions pair in the same compatible group,
scope and accounting window, acceptable coverage and nonzero cycles.
[perf stat documentation](https://man7.org/linux/man-pages/man1/perf-stat.1.html).

These tables do not prove PMU availability on any Pi. That requires the retained
actual per-board capability probe and repeated target experiments. ARMv6 and
AArch64 instruction streams are different; IPC/counts are diagnostic, not a
universal hardware-efficiency ranking. No power meter or extra sensor is used.
