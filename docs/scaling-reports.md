# Workload and output scaling

Use the unchanged `configs/experiments/scaling.json` for the proposed Pi
protocol: recorded spread selections of 100, 1,000, 10,000 and full input, minimal
and archive-full plotting, three independent sessions and ten attempts per
pair/size/profile/session. Calibrate the thermal gate and freeze the workload
on the actual boards first. This is a large experiment, not the first smoke run.

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/scaling.json --device-label pi5 --detach
```

After it finishes or is stopped, reconstruct from its saved directory:

```bash
python3 scripts/run_experiment.py report EXPERIMENT_DIRECTORY --output outputs/reports/pi5-scaling-first
```

## Intended variables and controls

`scaling_analysis` is an additional workload-comparison contract, not a merger
of primary equal-work cohorts. Only input selection size and frozen plot profile
are variables. Device/backend/source/historical input hashes/Python/packages/
selection method/thread/process/cache/thermal/observation/stop/retention controls
remain separate. Plot input hashes stay with their declared profile variable.
Only the manifest's `scaling` protocol is analyzed; acceptance/endurance jobs
are never renamed as scaling results.

Cost ratios change one dimension at a time: input size at the same exact
rendering contract, or plot profile at the same requested size. Changes in both
are not presented as one explained effect. Missing/inconsistent rendering
contracts cannot supply a ratio. Matched variants require the same independent
session identities for paired whole-session bootstrap intervals. One session
has no between-session uncertainty; adjacent attempts are not independent
resampling units. Ratios are workload cost ratios, not same-work device speedups.

## Saved results

`scaling.jsonl.gz` retains every scaling job, including warmups/failures/
exclusions, exact primary cohort, block/session identity, requested and actual
rows, selection coverage, all verified plot metadata and full-work metrics.
Failures with no products remain in the same requested variant's denominator.
Actual row counts come from verified saved arrays, never from requested-size
guesses. Original row IDs, duplicates and non-finite instrument values remain
unchanged in the retained scientific NPZ/input snapshots.

Each variant reports worker/cycle latency and per-input-row latency with
independent-session summaries. Per-row costs include fixed startup/output work;
they are not isolated model throughput or inferred algorithmic complexity.
Resource tables include summed complete stage CPU/I/O, sampled RSS maximum,
PNG payload bytes/count, logical/new-content bytes and parent retention costs.
PNG sizes come from the bound, hash-verified readable files themselves, not
assumed metadata values. Original metadata sizes and their agreement flags are
retained alongside the actual measurements.
A missing stage field keeps the whole-stage sum unavailable. Genuine zero I/O
stays zero. Sampled RSS can miss peaks; the largest successful size does not
establish a safe memory-capacity limit. Failed sizes remain visible.

Every job's plot products retain dimensions/format/rendering, geographic
context, variable/coordinate view, scales, complete filter specifications,
selected-point counts and empty-selection status, times and centroids where
requested. No existing scientific filter is removed to improve a benchmark.
A metadata example in the summary is explicitly only an example; per-attempt
differences remain in the compressed journal. PNG payload bytes are observed
output size, without any assumed radio, bitrate, transfer duration or power.
More selected points/images do not prove greater scientific utility or reliable
SAA identification; those remain scientific interpretation questions.

`scaling-*.png` shows filled scatter points for full-work latency, sampled RSS
and PNG payload versus actual completed input rows. Backend/control groups stay
separate; each profile/rendering contract remains distinct. Missing row/metric
values are not plotted at zero. Failure/exclusion counts stay in the caption.
The plots fit no extrapolated complexity or capacity curve.

## Local functional verification

`configs/verification/local-scaling-functional.json` is a deliberately small
LOCAL functional manifest: one pair, sizes 6/100, both profiles, one attempt each
and full four-pair scientific validation/reference acceptance. It uses
uncontrolled thermal settings because this PC has no Pi SoC sensor. It is not
a thermally controlled hardware-performance protocol or a proposed Pi pilot.

```bash
python3 scripts/run_experiment.py run --manifest configs/verification/local-scaling-functional.json --device-label local-pc-python314 --output-root outputs/verification/scaling-workflow
```

Actual Pi performance, thermal calibration, resource limits and cross-board
scaling conclusions require the boards' own retained results.
