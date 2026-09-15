# SUCHAI hardware and software benchmark completion plan

Status: proposed implementation plan, 2026-09-14. Source audit: `ffdfdaa`.
This document describes required additions and their acceptance criteria; it
does not certify the current benchmark as complete.

## Scope and equipment

Use the existing Pi Zero W (32-bit), Zero 2 W, Pi 4 and Pi 5 (64-bit), their
built-in temperature sensors, and software measurements available on each.
Use their existing storage, cooling and supplies. Power/energy measurement
is excluded. No additional hardware or external sensors are required.

Keep system Python installation with `--break-system-packages`, the proven
ApexPy ARM build fix, and independently selectable optional backends. Develop
and verify changes on the local PC before Pi dependency/acceptance tests.
Record differences between local and Pi runtimes explicitly.

The main unit of work is the complete historical processing chain:
measurements → TLE selection → orbit → magnetic coordinates and geographic
footpoints → analysis/filter selection → maps/tables → saved products.
Instrument stages inside that chain. A stage diagnostic does not replace an
end-to-end comparison. Preserve all existing scientific options and filters.

## What exists and what is missing

These findings come from source inspection, not a newly executed campaign.

| Area | Existing implementation | Required completion |
|---|---|---|
| Equal work | `comparison.json`: 5 measured repeats per backend pair; `stability.json`: 20 | Operator-selectable attempt count, independent sessions, explicit failure/retry accounting, detached support |
| Timed endurance | Repeated complete four-pair rounds, duration override, no cooldown | Scenario-specific sustained blocks, well-defined elapsed-time boundaries and interruption policy |
| Thermal control | Built-in temperature timeline, throttling flags, fixed delay/temperature target | Stable starting-condition gate, recovery between experiments, timeout handling, thermal trend analysis |
| Memory stability | Sampled process RSS and system RAM/swap; fresh child for each execution | Persistent-worker mode; worker and supervisor trends, file descriptors, threads, native memory and memory pressure |
| CPU and stages | Wall/process CPU time, frequency, faults, context switches, I/O for each stage | Consistent timer boundaries, sampling overhead calibration, thread/affinity policy, requested versus observed frequency |
| Hardware counters | Optional single `perf` run per pair; five requested events | Capability discovery, repeated counter experiments, event quality/scope, multiplexing accounting and ratios |
| Correctness | TLE/EOP/reference checks, orbit parity, magnetic diagnostics, full-profile certificate | Evidence on final dependency set; stronger scientific acceptance and cross-device numerical comparison |
| Comparisons | Settings/signature checks and combined summary CSV | Same-work output comparison, confidence intervals, independent-session analysis, thermal/failure plots |
| Retention | Timestamped runs, raw samples/arrays, compressed logs, snapshots, hard-link sharing, resume | Portable relative references, recovery/export verification, full cost accounting and measured storage forecasts |
| Operation | Master scripts, preflight, checkpoint, detached timed launcher | One experiment manifest/launcher for all modes; device-wide run lock; status/stop/resume for all modes |
| Reproducibility | Main package pins, source/input hashes, system inventory | Transitive dependency/build provenance and explicit classification of OS, ABI, threading and workload differences |

Specific audit findings:

- `_cooldown()` records `maximum_wait_reached` or an unavailable sensor and
  the caller still proceeds. The current 45°C ceiling does not demonstrate
  that two runs began at equivalent, stable thermal conditions.
- Every measured repeat launches a new Python process. This measures repeated
  batch execution; it cannot establish that a persistent worker has no leak.
- `parse_perf_stat()` keeps event values but drops counter running-time and
  multiplexing information. The counter run has no dedicated repeat protocol.
- `compare_sessions()` checks configuration and within-session consistency,
  but does not compare scientific arrays between devices or estimate speedup
  uncertainty. It also requires unique device labels, limiting repeated-session
  analysis for one board.
- `_run_child()` includes parent log flushing/reading in its external wall
  timer. `_retain_run()` records later compression/deduplication separately.
  These boundaries need explicit names before reporting total job throughput.
- The stage sampler collects at a requested 50 ms interval and retains lists
  of samples for extrema. Its overhead and memory growth have not been
  calibrated on the Zero W. Sampled RSS maxima can miss brief peaks.
- A global benchmark lock was not found. Two operators can launch overlapping
  jobs on the same Pi and contaminate the measurements.
- The documented local runtime and Pi runtime differ. The latest Pi traceback
  exposed Astropy/NumPy incompatibility; a corrected pin and mocked regression
  tests are not equivalent to successful execution of that full version set.

## Experiment definitions

Counts below are proposed starting defaults, not statistical guarantees.
Pilot durations on every board first, then freeze counts for the comparison.
An attempt is one scheduled execution; a round contains one attempt for each
selected backend pair. Warm-ups and validation runs have separate identities.

| Experiment | Work and stopping rule | Conditions and question answered |
|---|---|---|
| Acceptance | Small input through every pair, followed by full-data scientific validation | Does the installed program produce acceptable complete outputs? |
| Equal-work baseline | 3 independent sessions × 10 measured attempts per pair; 30 per pair in total | Start each attempt after thermal recovery; compare time and resources for identical work |
| Sustained operation | One backend pair repeated continuously for a selected duration, e.g. 4 hours | No cooldown inside a block; determine warm-up, temperature plateau, throttling and sustained throughput |
| Persistent-worker stability | Repeated full jobs in one worker, with fixed attempts or duration | Determine whether memory/resources grow while the satellite-style process remains alive |
| Hardware counters | Separate repeated complete jobs for supported event groups; initially 10 per pair/group | Explain execution using instructions/cycles and supported cache/branch events |
| Workload and output scaling | Fixed attempts at recorded dataset sizes and plotting profiles | Determine memory limits, per-row cost, plotting cost and saved/downlink product size |

The existing four combinations remain Astropy/AACGMv2, Astropy/ApexPy,
Skyfield/AACGMv2 and Skyfield/ApexPy. Persistent and fresh-process execution
must invoke the same scientific functions. They differ in process lifetime;
each iteration still recomputes orbit and magnetic results. Any reuse of
loaded inputs, TLE objects or model objects must be a declared, separately
validated software variant.

For fixed attempts, retain failed attempts in the denominator and report
scheduled, started, scientifically valid, failed, interrupted and skipped
counts. An automatic retry must receive a new attempt ID and reference its
original. Never silently keep retrying until N successes and call that N
attempts. Resume must preserve this accounting.

For duration runs, record requested duration, actual wall duration, worker
busy time, retention time, recovery time and completions. Define the duration
clock to begin after validation and initial recovery. Finish the active job
at the deadline; do not silently require extra rounds. Treat the existing
mixed-pair endurance mode as a separate workload from a single-pair block.

## Thermal scheduling with the Pis' own sensors

One benchmark job at a time per Pi. Implement a lock shared by all launchers,
validation jobs and profilers. Validation and compilation heat the board:
begin a fresh recovery period after either, before measured work.

On each board, measure an idle baseline using its built-in sensor. For the
equal-work experiment, a proposed initial gate is temperature within 2°C of
that session's idle baseline and absolute temperature slope below 0.2°C/min
for 60 seconds. Calibrate these proposed values against sensor resolution and
the pilot traces before freezing the protocol. Save the entire recovery
trace. A gate timeout marks the attempt unstarted/uncontrolled and pauses or
ends that experiment according to its manifest; it must not silently pass.

This gate provides reproducible starting conditions for a board. It does not
claim that all boards have identical temperatures. Record each starting
temperature and analyze temperature dependence explicitly. A later controlled
temperature-band experiment may use software workload heating and idle
recovery, but only for bands actually reachable on the boards; do not infer
causal thermal effects from an ordinary time trend alone.

Run the four pairs in a recorded balanced order across independent sessions,
with recovery between equal-work attempts. For thermal blocks, keep a single
pair active throughout a block, recover before the next block, and rotate
block order across sessions. This avoids making each pair's thermal history
depend on an arbitrary preceding pair. Blocking/randomization is supported
by the [NIST experimental-design guidance](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm).

Different Pis can run concurrently if each has independent local storage and
power and is not doing transfers or other shared work. Simultaneous starting
times are unnecessary. Preserve existing cooling and record fan mode and
other known configuration details; do not require new equipment.

The current 80°C stop policy may end a block before sustained throttling can
be studied. Define separate controlled-baseline and thermal-stress policies,
record the board's configured limits, and retain firmware thermal protection.
The protocol must state whether hitting the campaign threshold terminates the
test; a stopped block cannot establish a steady-state result. Raspberry Pi
documents temperature-dependent frequency reduction in its
[thermal-control documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#frequency-management-and-thermal-control).

## Measurement contract

Every value needs a unit, scope (stage, worker, supervisor or whole board),
source, timestamp and availability status. Missing/denied/unsupported values
are distinct from zero. Preserve actual acquisition times and gaps.

| Category | Required measurements and interpretation |
|---|---|
| Time | UTC identity plus monotonic durations; launch/import, each stage, worker exit, output finalization and full job cycle; latency and valid jobs/rows per second |
| CPU | User/system CPU seconds, per-core board utilization, worker CPU equivalents, active threads, migrations/context switches, governor and frequency policy |
| Temperature | Built-in SoC temperature throughout idle, recovery and execution; initial/peak/final, time series, heating slope, plateau evidence, current/historical throttle flag transitions |
| Memory | Sampled RSS plus kernel process high-water mark where available; lower-rate PSS/USS where supported; worker/supervisor separately; RAM, swap, faults, descriptors and threads |
| I/O and storage | Worker read/write bytes, logical I/O, output sizes, compression time/ratio, physical allocated storage after sharing, free bytes/inodes and filesystem details |
| Hardware counters | Instructions, cycles, task-clock and supported cache/branch events; event scope, availability, measurement coverage and repeated values |
| Correctness | Input/output row counts, domain/invalid counts, numerical differences, plot selections, saved-product integrity, failures and timeouts |
| Observation cost | Sampler CPU/RAM/I/O, actual cadence/gaps, overhead relative to minimally instrumented identical jobs |

Report frequency sources separately. Linux warns that `scaling_cur_freq`
often describes the last requested state rather than actual hardware
frequency. Capture that plus firmware-reported Arm clock when available,
without treating sampled clock values as instruction counts.
[Linux CPU frequency documentation](https://docs.kernel.org/admin-guide/pm/cpufreq.html#policy-interface-in-sysfs).

Add CPU/memory/I/O pressure when `/proc/pressure` is available. PSI records
time stalled on resources and helps distinguish memory or I/O pressure from
slow computation. It is a capability-dependent software measurement.
[Linux PSI documentation](https://docs.kernel.org/accounting/psi.html).

Probe `perf` and actual supported events per board/kernel. Save raw results,
event definitions, user/kernel scope, enabled/running time and scaled values.
Prefer small event groups so counters can run together; reject or label poor
coverage. Compute instructions/cycle only from compatible scopes and matched
measurements. Instruction counts across ARMv6 and AArch64 describe different
executed instruction streams and are not a universal efficiency ranking.
[perf stat documentation](https://man7.org/linux/man-pages/man1/perf-stat.1.html)
and [perf event accounting](https://man7.org/linux/man-pages/man2/perf_event_open.2.html).

Hardware counters are required where exposed by the board/kernel and
permissions; when unavailable, record the reason and retain the software
metrics. Their absence must not invent values or prevent a basic timing test.
Repeated counter collection must have its own recovery policy. Heavy profiling
and primary timing do not execute concurrently on a board.

Define instrumentation levels: external timing/minimal observation, normal
stage telemetry, and detailed profiling. Execute matched jobs to quantify
overhead per board. Retain all samples actually acquired in every level;
choosing a lower sampling rate must never delete earlier samples. Replace
in-memory sample histories used only for extrema with streaming aggregates.
Report measured overhead; do not subtract an assumed constant from timings.

## Software, hardware and workload controls

Record source/input hashes, the complete runtime dependency closure, native
wheel hashes, compiler/build options, BLAS implementation, Python/OS/kernel,
firmware, architecture, CPU governor, affinity, thread limits, swap/zram,
filesystem, storage configuration and known cooling configuration.

Use a declared one-thread numerical-library baseline and separately test the
board's normal threading configuration. Record effective library thread
counts, not only environment variables. NumPy's BLAS backend can use multiple
threads independently of Python-level parallelism.
[NumPy global configuration](https://numpy.org/doc/stable/reference/global_state.html).
Treat scheduler/frequency tuning as a named experiment configuration; preserve
the actual stock setup for deployment measurements. The
[pyperf system guide](https://pyperf.readthedocs.io/en/latest/system.html)
explains why frequency, affinity and competing tasks affect measurements.

Compare the existing board-plus-software systems, acknowledging that the Zero
W requires 32-bit ARMv6. Do not call the comparison isolated silicon speed.
Keep common source/library versions when supported; any unavoidable package
or algorithm variant is explicit and compared separately. Build/install
availability on the Zero W must be demonstrated before claiming support.

Define fresh-process and persistent-process modes independently from file
cache state. Repeated fresh processes can still benefit from OS file caches.
Use an explicit warmed-cache baseline; label first-start observations and
any separately designed cold-cache experiment. Do not automatically drop
system caches or change OS settings during ordinary runs.

Scaling profiles should use recorded selections of the trusted data, initially
100, 1,000, 10,000 and the full canonical rows where available. Preserve row IDs,
time/region coverage, duplicates and legitimate non-finite instrument values.
Tiny prefixes serve smoke tests, not representative science workloads.

Compare the current minimal maps and complete archive-parity plot profile as
different named workloads. Record resolution, projection, filled markers,
continents, color scales, filters, selected rows, format and bytes. Future
plotting implementations must pass the same selection/scientific checks.
Measure the trade-off between output size, execution time and visible
scientific information. Optional link-budget calculations may use a supplied
bit rate later; current output-byte measurements need no radio assumptions.

## Scientific acceptance and reliable execution

Preserve and extend the existing validation contract in
[full-code-validation.md](full-code-validation.md): trusted columns, TLE
checksums/identity/epoch assignment, offline EOP, reference SGP4 vectors,
Astropy/Skyfield agreement, magnetic conversions, footpoints and all filters.
Retrospective TLE selection still allows epochs after the observations.

Add boundary cases, explicit coordinate units/frames/time conventions,
longitude and MLT wrapping, magnetic domain masks and expected invalid rows.
Validate each magnetic model against its own invariants/reference cases;
ApexPy and AACGMv2 coordinates are not expected to be numerically equal.
Both orbit paths share SGP4, so their agreement alone is not independent
absolute orbit accuracy. Preserve that limit in reports.

Compare scientific outputs between boards using justified, frozen tolerances
and exact row/selection identity. Exact hashes remain useful for retained
bytes and deterministic repeats; image hashes alone cannot establish
scientific agreement across platforms. Validate images as readable products
with expected dimensions, selected counts, plotted data and geographic context.

Exercise interruption, child failure, timeout, unavailable sensor/counter,
disk exhaustion, malformed input, clock adjustment and resume in local tests.
Differentiate computational failure, failed scientific validation, missing
measurement and unmet thermal condition. Partial campaigns remain partial.
Test repeated invocation of the persistent worker with a bounded memory
budget and cleanup of figures, files, threads and backend state.

Keep immutable dated attempt directories, compressed scientific arrays,
raw telemetry, logs, source/input snapshots and failure records. Add portable
relative file references and an export/import verification command. Measure
storage growth in a pilot on each board; show a forecast using actual bytes
per attempt and free space. Retention work contributes to full-cycle latency
and sustained throughput. A preflight estimate and between-run checks do not
guarantee that a single large job will fit; reserve headroom accordingly.

Do not promise zero loss on sudden power failure. Verify committed records
and recover partial ones after restart; document the measured/implemented
flush boundary. Retain every recoverable record rather than deleting failures.

## Analysis deliverables

Produce reports from the saved raw attempts, with a comparison contract that
separates intended variables from controlled settings. Support multiple
sessions from the same board; preserve session and block identities.

- Per-pair end-to-end latency, full-cycle latency, stage contributions,
  throughput, completed-work counts and failure rates.
- Median, spread, sample count and confidence intervals for latency/speedup.
  Analyze independent sessions/blocks; adjacent hot-loop repetitions are
  correlated. Use a declared resampling method and seed, and label estimates
  from small samples. Thirty attempts is a starting budget, not proof of
  precision. Report p95 only with its sample count and uncertainty.
- Time/temperature/frequency/throttling plots; warm-up versus sustained
  performance; outcomes versus both elapsed time and attempt number.
- Worker and supervisor memory/resource trends; distinguish retained caches,
  swap pressure and steadily growing live state before diagnosing a leak.
- Counter and I/O tables with availability/quality, output size and compression
  costs, measurement overhead, and numerical agreement between boards.
- Explicit incomplete/invalid/excluded classifications with all original
  records retained. A failure must not disappear into a timing average.

## Implementation order and completion gates

| Step | Deliverable | Evidence required before calling it complete |
|---|---|---|
| 1. Freeze the experiment contract | Versioned manifest with workload, stop rule, process mode, repeats/sessions, thermal/thread/cache/instrumentation policies | Example manifests reviewed; exact count/failure/time semantics tested; no ambiguous override |
| 2. Establish scientific/runtime acceptance | Final package matrix and complete validation on local PC; reproducible install instructions for supported Pi targets | Real local pipeline outputs and dependency versions recorded; mocked tests explicitly identified; target acceptance reported separately |
| 3. Finish orchestration | One master entry point for every manifest with foreground/detached, status, graceful stop and resume; device lock | Small real campaign plus interruption/resume and overlapping-launch tests; exact attempt accounting |
| 4. Finish measurement boundaries | Worker/stage/full-cycle timing, streaming sampling, supervisor metrics, availability schema | Controlled timer tests; measured observation overhead; correct compressed raw records and portable export |
| 5. Implement thermal protocols | Stable recovery gate, balanced ordering, scenario blocks, declared threshold behavior | Local replay tests for sensor traces; Pi acceptance confirms actual sensor/clock behavior |
| 6. Add persistent execution and repeated counters | Same scientific chain in a long-lived worker; capability-aware counter experiments | Numerical parity between process modes; resource cleanup tests; real supported counter evidence per Pi |
| 7. Complete comparison/reporting | Equal-work and thermal reports, cross-device numerical checks, uncertainty and workload scaling | Reports reconstructed entirely from saved records, including failures and unavailable metrics |
| 8. Validate the operator workflow | Documented install → acceptance → fixed-work comparison → sustained test → export/report | Successful small complete workflow on every supported board; then the declared longer experiments |

Each step includes function documentation, operator documentation, meaningful
tests and saved verification evidence. Keep existing working paths while
adding missing modes. Hardware-specific dependency setup stays on the Pis;
scientific and orchestration fixes are developed and verified locally.

The first implementation milestone is steps 1–5: a defensible equal-work
comparison with complete thermal and resource records. The benchmark is not
declared complete at that milestone. Completion requires steps 6–8 as well,
with explicit per-board capability results and evidence for every promised
mode. No generic claim of "everything validated" substitutes for that matrix.
