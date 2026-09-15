# Benchmark metrics and interpretation

The benchmark separates every computational and output stage. Plotting is not
given special treatment: it records the same CPU, memory, I/O, frequency, and
thermal fields as orbit and magnetic calculations.

## Recorded for every stage

- UTC start and finish timestamps;
- monotonic wall time;
- process CPU time, split into user and system time;
- CPU-equivalent percentage (`100 × process CPU / wall time`);
- sampled peak resident memory and resident-memory change;
- process I/O bytes and I/O characters where Linux exposes them;
- voluntary and involuntary context switches;
- minor and major page faults;
- peak process thread count;
- system-available RAM at start, minimum, and end;
- load average at stage boundaries;
- SoC temperature at start, sampled maximum, and end;
- sampled CPU-frequency minimum and maximum;
- Raspberry Pi throttling flags at start and end.

The whole child process also has an external wall time and system snapshots
before and after it. `child-timing.json` defines launch-through-exit timing,
including startup, imports, processing and worker output writes. It separately
records parent log setup/flush; those costs do not enter worker wall time.
Timer-boundary version 2 records `precommit_cycle_seconds` in the immutable
run record and `full_cycle_seconds` in `cycle-timing.json` after committing the
run record, terminal event and checkpoint. Reports reload that sidecar. The
full job cycle includes scheduling, worker execution, product checks, raw
observations, compression/sharing and those operational commits. Its own
measurement-sidecar write happens after the boundary and still contributes to
actual campaign elapsed time/throughput. Thermal recovery, session validation,
persistent-worker startup/shutdown and session reporting remain separately
identified costs, not secretly included in per-attempt latency. A recoverable
attempt without a committed timing sidecar has unavailable cycle timing.
Legacy boundary-version-1 records keep their narrower timing interpretation.
Automatic master/API operation costs and optional external command startup/exit
and log-finalization clocks are documented in
[whole-operation-costs.md](whole-operation-costs.md). Their containing scopes
must not be added to job/stage/API sub-times. Detached child interpreter/stdlib
bootstrap is explicitly outside its automatic master clock; do not invent it.

The post-job thermal safety check runs after the committed cycle boundary.
Its extra acquisition and a thermal-stop state commit contribute to block/API
wall time, not the already committed per-attempt cycle. See
[thermal-stress.md](thermal-stress.md) for the sampled-event latch and separate,
trace-bound recovery call costs. Protocol elapsed time ends at the terminal
sample; compression/receipts are accounted for by actual call/block clocks.

Stage CPU, I/O and context/fault boundary counters are read before sampler
shutdown, final sampling and journal sync. Sampling during execution contributes
to the measured cost. Extrema use constant-size aggregates; all acquired rows
still go to disk. Timer/counter reads are sequential acquisitions, not an atomic
kernel snapshot.

Long campaigns additionally append a continuous UTC system timeline at the
configured interval. It contains the active run identifier, phase, SoC
temperature, CPU frequency and utilization, available and used memory, swap,
one-minute load, and free storage. These raw samples are retained globally and
in the corresponding run directory; stage start/maximum/end summaries do not
replace the raw thermal record. Finished run timelines and campaign segments
are losslessly gzip-compressed.

The faster stage sampler also retains every acquired row in
`benchmark-<backends>.samples.csv.gz`, with UTC/monotonic timestamps and
cumulative CPU, I/O, context-switch and fault counters alongside memory,
temperature and frequency. It requests 50 ms sampling; actual timestamps are
authoritative when scheduling delays occur. Firmware throttling is polled at
stage boundaries and in the slower system timeline. Sampling errors are
recorded; persistence failures are fatal rather than silently losing data.
See `raw-data-retention.md` for compression, exact array retention and storage.

Each board timeline row has `observations_json`: individually timestamped
readings with value, unit, scope, source, status and reason. It includes
supervisor CPU/resources, kernel process-lifetime `VmHWM`, file descriptors,
PSS/USS, RAM/swap, PSI, filesystem space/inodes and per-core accounting.
Stage rows have `process_observations_json` with the same contract for the worker.
PSS/USS and firmware clock are acquired at a lower rate; `not_sampled` readings
are not filled with earlier values. CPU percentages need two cumulative
observations and initially have status `initializing`.

Kernel `VmHWM` is a lifetime peak and must not be labelled a stage-specific
maximum. CPUFreq `scaling_cur_freq` is labelled requested frequency; firmware
`measure_clock arm` is a separate observed reading. Missing/denied capabilities
keep their status rather than a fabricated zero. The enriched normal sampler's
overhead still needs matched-job calibration before a timing comparison claim.

## Optional Linux `perf` counters

With `collect_perf`, a separate non-timing run requests `cycles`,
`instructions`, `task-clock`, context switches, and page faults. Hardware and
kernel security settings may make counters unavailable; the report records
that explicitly rather than substituting zero. Installing or authorizing
`perf` is an OS-administration decision and is not silently performed by the
benchmark.

The separate `perf` run disables PCS SUCHAI's stage sampler so monitoring
threads do not contaminate the hardware counters. It is not used in the normal
wall-time summary.

The legacy counter path remains a single diagnostic, explicitly labelled as
such. It now uses `--no-scale`, preserving exact integer counts and coverage.
`accounting` retains event scope, running nanoseconds, rounded running coverage,
quality, inferred enabled-time bounds and scaled estimates. Enabled time derived
from rounded coverage is an estimate, not an exact kernel reading. The unified
[manifest launcher](manifest-experiments.md) implements repeated small-group
counter experiments and capability discovery. Short native local execution
recorded the actual absent `perf` executable; it did not measure a Pi PMU.
Per-board supported-event evidence remains required. See
[Pi handoff](pi5-handoff.md) for the separate software installation/probe step.

Instructions/cycle is permitted only for acceptable counters in one simultaneous
group with matching scope/accounting windows. The legacy ungrouped diagnostic
does not establish those conditions. Raw field layout follows the
[perf stat documentation](https://man7.org/linux/man-pages/man1/perf-stat.1.html);
running/enabled reporting follows the
[Linux perf implementation](https://github.com/torvalds/linux/blob/master/tools/perf/util/stat-display.c).

## Scope of available measurements

Electrical power and energy are excluded from this project’s benchmark.
Temperature readings come from the Pi's built-in SoC sensor. Available system memory also
includes Linux filesystem cache, so a decline is a diagnostic signal, not by
itself proof of a memory leak.

## Throttling flags

Raspberry Pi firmware flags may contain both current and historical events.
Preserve the hexadecimal value. A run affected by current undervoltage,
frequency capping, or thermal throttling should be analyzed separately and not
silently averaged with unaffected runs.

## Repeat interpretation

Median is the primary robust timing summary. Report spread and individual run
order as well: an isolated fast median can conceal heating, caching, or
background activity. Warm-ups are saved but excluded from measured summaries.
Scientific CSV hashes must agree across identical repeats; timing results from
an inconsistent scenario are rejected by the command's nonzero exit status.
