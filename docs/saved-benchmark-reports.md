# Reports from saved experiments

Run reporting on the analysis PC after transfer, using its existing Python.
It does not rerun scientific calculations, install dependencies, or change the
original experiments. On a Pi, reporting holds the same device lock as running
an experiment: do not run both concurrently. Report directories must be new
and outside all source experiments. No original benchmark is deleted.

```bash
python3 scripts/run_experiment.py report outputs/imported-pi5-experiment --output outputs/reports/pi5-first --seed 1729 --resamples 2000
```

Pass multiple experiment directories to compare them. Repeated sessions from
one board are supported; unique device labels are not required. Passing the
same experiment or its imported copy twice is rejected, rather than inventing
another independent session.

```bash
python3 scripts/run_experiment.py report outputs/imported-pi5-session1 outputs/imported-pi5-session2 outputs/imported-pi4-session1 --output outputs/reports/pi4-pi5-first
```

## What is retained and checked

The reader inventories dated attempt directories, not just successful runs in
a final summary. It retains warm-ups, failed/interrupted slots, terminal
orphans, damaged records, duplicate slots and checkpoints referencing missing
attempts. It never mutates recovery sidecars or retries work. Missing cycle
commit timing remains unavailable. A stopped experiment remains partial.

Before controlled grouping, the reader verifies the frozen source inventory,
every archived source member and every compressed/decompressed input snapshot
against their recorded hashes and sizes. Original external input paths are not
accessed. Imported inventories additionally undergo the portable byte audit.

Every complete candidate's declared artifacts are hash checked. Unrounded
arrays undergo required-field, precision, row, coordinate-unit/domain and
magnetic-model invariant checks. Trusted measurements, timestamps, headers,
selected source rows and nearest-TLE assignments are compared exactly against
the verified historical input snapshots. Later TLE epochs remain eligible.
All saved configured plot recipes/masks/axes/values/labels/scales are checked
against the frozen profile and saved coordinates, including legitimate empty
filters. The default geographic, magnetic and footpoint images must be bound
to their retained artifacts; PNGs are decoded and checked against actual masks,
dimensions, filled-marker metadata and geographic context.

When a full-data certificate is present, it is also checked against the
experiment's **archived** source/runtime and all three historical input hashes.
Its unlimited full-input/32-canonical-recipe flags and every required criterion
must pass. All four reference pipelines' retained artifact bytes, source rows,
TLE assignments, stage order, plot decisions and readable images are rechecked.
Today's checkout need not match a historical archive; the archive must match
its own frozen evidence. A present inconsistent certificate is failed evidence,
not silently treated as an optional missing certificate.
New reference-enabled source snapshots additionally require contract version 2,
both published magnetic regression gates and their hashed compressed raw reports.
Readers replay the archived fixed case values/tolerances and re-audit production
bridge invariants from raw values without loading archived native code. Verified
older source keeps its original thirteen-gate contract; dropping new flags or
criteria does not downgrade newer source. See
[magnetic reference acceptance](magnetic-reference-validation.md) for the
regression-versus-physical-accuracy distinction and complete retained fields.

Every candidate, including the first attempt, is then compared with its own
backend pair's accepted full-data arrays. Prefix/spread/full workloads project
the reference using exact source-row identity. A different frozen plotting
profile is reconstructed on the full reference's saved coordinates, then
projected to those same rows; native orbit/magnetic models are not rerun during
reporting. Empty filters remain valid recipes. Instrument values/TLE choices/
masks/labels are exact; only derived coordinates use the declared frozen
same-backend tolerance. Repeated identical but wrong outputs cannot establish
their own acceptance merely by agreeing with the first repeat.

The launcher performs this check after measured blocks and worker shutdown,
saving `acceptance/<segment>/workload-acceptance.json` and the complete compressed
per-attempt decision journal. Its wall/CPU cost is separate from worker latency,
committed cycle latency and the measured duration budget. Original attempt
records are not rewritten. Failed/incomplete exact-workload acceptance prevents
the experiment root from claiming completion. Reporting independently rechecks
the evidence rather than trusting that summary.

The report contains:

- `experiment-report.json`: scheduling/counts, controlled cohorts, stage and
  whole-worker/full-cycle statistics, speedups, matched observation overhead,
  scalar resource/temperature trends and explicit availability/exclusion limits.
- `attempts.jsonl.gz`: every inventoried attempt and its detailed integrity,
  trusted-input, filter, image and full-reference workload checks, including
  failed/partial outcomes.
- `stages.jsonl.gz`: stage records read from verified saved benchmark products,
  not the precomputed session averages.
- `resource_analysis` and `hardware-counters.jsonl.gz`: outcome-aware stage I/O,
  fault/context-switch tables and reparsed repeated perf records, with exact
  counts, availability and coverage. See [resource-reports.md](resource-reports.md).
- `scaling_analysis`, `scaling.jsonl.gz`, `scaling-*.png`: declared input-size/
  plot-profile full-work cost comparisons, exact saved plotting contracts and
  failure counts. See [scaling-reports.md](scaling-reports.md).
- `recovery_costs`, `recovery-costs.jsonl.gz`: unique trace-bound baseline/gate
  wall/CPU calls, unmet conditions and unavailable partial/legacy receipts.
  See [thermal-stress.md](thermal-stress.md).
- `observations.jsonl.gz`: all acquired CSV observations from block journals,
  including structured values, individual timestamps, sources, scopes, units
  and unavailable/denied/not-sampled statuses. Per-attempt copies are not counted
  again when the complete block journal exists. Corrupt/torn journals are
  explicitly listed, with their original files unchanged.
- `numerical-comparisons.jsonl.gz`: complete same-work/same-backend field and
  plot-decision comparisons under the frozen tolerance policy. Detailed results
  are streamed to disk, rather than accumulated in report RAM.
- `observations-*.png`: temperature, separate requested/firmware-observed
  frequency, worker/supervisor RSS/PSS/USS and timed attempt outcomes. Backend
  pairs have distinct markers/labels; warm-ups and excluded outcomes remain
  distinguishable. Missing sensors are annotated, not plotted at zero.
- `thermal-windows.jsonl.gz`, `throttle-transitions.jsonl.gz`, `thermal-*.png`:
  complete/partial observed-span temperature windows, exploratory candidate
  plateaus and separate sampled current/historical firmware states/transitions.
  See [thermal-reports.md](thermal-reports.md) for the criteria, availability,
  stopped-block, legacy-clock and no-exposure-inference contract.

Display envelopes retain first/last/min/max sampled points in progressively
merged acquisition bins; each channel declares original/display sample counts
and bin width. This bounds timeline plotting memory. It never prunes raw data.
Scatter marks avoid interpolation across acquisition gaps/process replacements.
New journals retain the segment's monotonic elapsed anchor, allowing each
reading's own acquisition time to set the elapsed axis. Historical journals
without that anchor use their saved sample-context elapsed clock, explicitly
labelled as not the individual acquisition time. No duration is inferred from
UTC timestamps. Resource slopes retain source/process and segment identity;
clock regressions suppress a slope. A trend alone does not prove a leak,
thermal causality or a temperature plateau.

## Comparison and uncertainty contract

The intended device variable is the **board-plus-software system**, not isolated
silicon. OS/kernel/ABI/architecture differences are reported explicitly. Source,
input hashes, Python/library versions, row selection, filters/plot profile,
thread/process/cache policy, governor, thermal protocol, observation level,
counter group and stopping rule must match for a primary timing cohort.
Unmatched settings remain visible as separate cohorts. Numerical checks also
span intentionally different observation levels/process lifetimes/thread limits
when the scientific work itself is identical. ApexPy is never numerically
scored against AACGMv2 as if they were the same magnetic model.
Full-reference-accepted timing and optional-certificate diagnostic timing use
different evidence cohorts. Missing required reference evidence or failed
present evidence excludes that attempt from accepted latency estimates, while
preserving its original status/bytes and detailed failure explanation.
Evidence cohorts use the experiment's reference availability, not whether a
particular attempt succeeded. Failed/interrupted attempts under those same
work/measurement controls stay in that cohort's started denominator.

The primary estimator is the median of the independent session medians, giving
sessions equal weight. Attempt median/IQR/p95/counts are also reported.
Confidence intervals use a percentile bootstrap resampling **whole sessions**,
with the declared seed and resample count; adjacent jobs are not resampled as
independent observations. Unequal original session sizes remain explicit.
One observed session cannot establish between-session uncertainty: its
intervals are unavailable. Fewer than five sessions is explicitly labelled a
small sample. P95 includes its count and session-bootstrap interval, but a
small sample does not establish tail precision.

Cross-device speedup is reference latency divided by candidate latency; values
above one mean the candidate is faster. Its interval independently resamples
each device's sessions. Declared overhead experiments instead pair the exact
same sessions across minimal/normal/detailed levels. Incomplete pairing has no
paired estimate. Overhead is the observed percentage change versus minimal;
an assumed overhead constant is never subtracted from ordinary timings.

Failures stay in the started denominator and original journals but not the
successful-job latency average. Worker-busy and committed-cycle throughput are
explicitly labelled: they are **not** campaign throughput including failures,
recovery, startup/shutdown and reporting. Full-cycle timing follows the saved
version-2 commit boundary, with missing commits unavailable.

## Current completion limit

The report is classified `diagnostic_saved_record_analysis`, not a complete
scientific/hardware acceptance certificate. Byte checks, own-model invariants
and relative numerical fidelity cannot independently establish physical model
truth. Full-reference workload acceptance is software fidelity, not independent
physical model truth or Pi capability acceptance. Additional independent
magnetic references, pilot-calibrated thermal evidence, cost/scaling forecasts,
the complete local mode matrix and actual per-board acceptance remain part of
the completion plan. The report command's exit code is 2 for partial/excluded
input and 0 for a created diagnostic report; neither means the entire plan is
complete. See [benchmark-implementation-status.md](benchmark-implementation-status.md).
