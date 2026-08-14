# Benchmark metrics and interpretation

The benchmark separates every computational and output stage. Plotting is not
given special treatment: it records the same CPU, memory, I/O, frequency, and
thermal fields as orbit and magnetic calculations.

## Recorded for every stage

- UTC start and finish timestamps;
- monotonic wall time;
- process CPU time, split into user and system time;
- CPU-equivalent percentage (`100 × process CPU / wall time`);
- peak resident memory and resident-memory change;
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
before and after it. The external value includes interpreter startup and import
costs; the stage values explain where time was spent.

Long campaigns additionally append a continuous UTC system timeline at the
configured interval. It contains the active run identifier, phase, SoC
temperature, CPU frequency and utilization, available and used memory, swap,
one-minute load, and free storage. These raw samples are retained globally and
in the corresponding run directory; stage start/maximum/end summaries do not
replace the raw thermal record.

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

Derived quantities such as instructions per cycle may be calculated only when
both counters are available. Compare counters from the same workload and
package versions.

## What software cannot measure alone

Energy and electrical power require an external USB power meter, current/voltage
sensor, or instrumented supply. CPU utilization is not a valid substitute for
watts or joules. Until a synchronized power sensor is integrated, record its
model and manually measured conditions in the session notes; do not claim an
energy result from PCS SUCHAI's internal metrics.

The firmware temperature is the SoC sensor, not ambient temperature. Record
room conditions when thermal conclusions matter. Available system memory also
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
