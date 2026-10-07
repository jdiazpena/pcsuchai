# Scientific output policies

The complete pipeline always loads measurements, selects historical TLEs,
calculates orbit positions, converts the selected magnetic model, maps geographic
ground footpoints, applies every configured filter, and renders the requested
images. `output_policy` controls saved scientific files. It is independent of
plot profile, observation level, orbit backend, and magnetic backend.

| Saved product | `onboard` | `validation` |
|---|---|---|
| Requested PNGs, including geographic footpoints | Yes | Yes |
| Settings, library versions, input identifiers, status/errors | Yes | Yes |
| Processed/valid/invalid counts and selected/plotted counts | Yes | Yes |
| Recorded in-memory orbit/magnetic/selection domain checks | Yes | Yes |
| Orbit and magnetic position CSVs | No | Yes |
| Per-row scientific arrays in `raw-products-*.npz` | No | Yes |
| Per-plot masks and coordinate/value arrays in `*.selection.npz` | No | Yes |
| Every acquired benchmark sample, logs, failures and interruptions | Yes | Yes |

`onboard` is the production CLI default. Normal benchmark experiments explicitly
select it in `workload.output_policy`; this includes equal work, sustained,
persistent, counters, scaling, overhead and thermal stress. Acceptance explicitly
uses `validation`, including its full four-pair, 26,725-row, 32-recipe reference
checks. The Python `run_analysis`/`run_benchmark_suite` APIs retain their historical
`validation` default for existing callers. New callers should always state the
policy. Older saved manifests without this field keep their original bytes,
hashes, block paths and behavior; reports label them
`historical_implicit_validation`.

## Choose the output without changing the workload

Use the already installed interpreter, from the repository root:

```bash
python3 -m pcsuchai analyze --orbit-backend astropy --magnetic-backend apexpy --plot-config configs/plots/archive-full.json --output-policy onboard --output-dir outputs/my-new-onboard-run
```

Add `--benchmark` to acquire worker stage observations. Choose a new output
directory each time. No plotting recipe is removed by choosing onboard output:
the full profile still produces 32 configured images plus three default maps.
A minimal plot profile remains a separate workload choice.

For detailed numerical files, use the same command with `--output-policy
validation` and another output directory. The complete acceptance path remains:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/acceptance.json --device-label DEVICE_LABEL
```

Run acceptance before the ordered pilot/benchmark sequence documented in
[Raspberry Pi benchmark workflow](raspberry-pi-benchmark-workflow.md). Validation
setup and reference audits have separate recorded costs outside worker and
measured campaign clocks. Measured onboard attempts do not generate the detailed
reference products again.

## What an onboard completion check proves

The worker checks row lengths, coordinate domains, error-code/finite-value
consistency, footpoint-height conventions, and finite selected plot values while
arrays are still in memory. It records only checks and counts. The supervisor
verifies the complete stage sequence, settings, counts and requested PNGs. Saved
reports also bind frozen recipes and selected-row digests to the retained input
snapshots, then decode images and verify dimensions, count metadata and map
context. Failures retain a small settings/error manifest and partial files.

When a full acceptance reference exists, an onboard summary can be checked
against that reference's projected valid/selected counts. Reports label this
`onboard_summary_reference_checked`, separately from detailed numerical workload
acceptance. Matching counts cannot establish per-row coordinate equality,
identical Boolean masks, or that every overlapping point is independently
visible in a PNG. Numerical repeat/cross-device comparisons are explicitly
unavailable for onboard attempts; detailed numerical comparisons use validation
products. Neither mode establishes absolute physical orbit/model truth.

Output policy participates in workload/cohort identities. Onboard and validation
timings are not silently combined. The overhead/scaling/thermal reports keep
this control while varying only their declared independent variables.

## Benchmark retention

Both policies retain every acquired timing, CPU, memory, temperature, frequency,
throttling, counter and availability observation. Normal/detailed instrumentation
retains raw stage samples; minimal instrumentation does not acquire those stage
samples, but the independent supervisor/board timeline remains. Its overhead
must be measured under the same intended observation settings across devices.
No samples are pruned or replaced by summaries. Input/source snapshots are
campaign evidence outside the worker's scientific products.

## Local verification

```bash
python3 -m pytest tests/test_output_policy.py
python3 scripts/verify_output_policy.py
```

The second command creates a new timestamped local directory. It runs both
policies on the full dataset and all 32 recipes for each of the four backend
pairs. It hashes actual in-memory measurement/TLE/orbit/magnetic/plot-selection
arrays, compares every image's bytes, checks saved products, and records actual
file inventories/sizes in `verification.json`. These are local functionality
and storage observations, not Raspberry Pi performance measurements.

### Inspected local evidence — 2026-10-07

The existing Miniconda Python 3.14.7 ran the complete suite: **572 passed**,
zero failures/errors/skips, in 305.09 seconds. Retained evidence:
`outputs/verification/output-policy-final-tests-uBohyr/full-tests.xml` and
`full-tests.log`. The 942 upstream plotting/date/cache warnings remain visible;
no dependencies were installed or warnings suppressed. Earlier failed test
logs remain retained separately, not replaced by this successful result.

The full-data verifier returned exit zero and `passed: true` at
`outputs/verification/20261007T180336.701656Z-output-policy/verification.json`.
It compared 26,725 rows, all 32 configured selections and all 35 PNGs per pair.
Every actual in-memory field digest and PNG SHA-256 matched between policies.
The executable-source digest is
`edc307b87ab2dfac3a2e9676c85057f443ac635f53b71731682808031c7975ba`
(123 inventoried files).

| Backend pair | Validation bytes | Onboard bytes | Reduction |
|---|---:|---:|---:|
| Astropy / AACGMv2 | 39,324,255 | 12,559,875 | 68.06% |
| Astropy / ApexPy | 37,365,539 | 12,504,886 | 66.53% |
| Skyfield / AACGMv2 | 39,269,003 | 12,560,856 | 68.01% |
| Skyfield / ApexPy | 37,418,989 | 12,509,455 | 66.57% |
| Total | 153,377,786 | 50,135,072 | 67.31% |

These are logical file bytes in the local analysis product trees, including
acquired worker observations and any runtime cache. They exclude campaign
setup/reference snapshots, supervisor timelines and export operation costs.
They are not an archive-size prediction, target storage forecast, elapsed-time
speedup or Pi thermal measurement. PNGs remain the dominant onboard products;
the plot profile was deliberately **not** reduced. Minimal plots are still an
independent option. Acceptance keeps its detailed files and can still make a
large archive; the reduction applies to routine onboard measured products.

The native policy tests cover all four pairs, exact array/selection/image
parity, stage/settings/count/image damage, retained failures, no overwrite,
minimal/normal/detailed observation levels, and real repeated fresh/persistent
workers with warmups, gzip samples, export/import and saved reporting. The
comparison tests reject mixing output policies. Historical missing fields retain
their old interpretation and hashes rather than being inserted into old JSON.

The normal foreground local acceptance master returned exit zero and root
status `complete` at
`outputs/verification/output-policy-acceptance/local-output-policy/2026/10/07/20261007T180654.877068Z-acceptance/`.
All four scheduled smoke attempts started and received detailed numerical
reference acceptance, with no failures, interruptions, retries or skips. Its
`validation/20261007T180710.189011Z/full-validation-certificate.json` passed all
15 gates for the full 26,725-row/four-pair/32-recipe workload. A separate post-exit
call to `verify_validation_certificate` passed all 18 source/runtime/input/
contract/artifact checks and all four backend artifact audits. The root records
the same 123-file source digest above. Detailed postmeasurement acceptance costs
are separately retained, not charged to measured worker/campaign clocks.

The unchanged historical Pi 5 import was reverified: all 443 payload files and
152 images across eight manifests passed. Reporting still accepted four of four
measured attempts numerically and explicitly labelled their output policy
`historical_implicit_validation`. Every original file, including the two import
metadata files (445 total), had the same SHA-256 before and after the actual
report API call. The new report is outside that immutable import:
`outputs/verification/20261007T181145.107835Z-historical-output-policy-report/experiment-report.json`.
A preceding observer used the wrong result-key name after its report completed;
that unsuccessful observation and its separate report remain retained. It was
not a scientific failure or an excuse to rewrite historical evidence.

### Six-step completion audit

| Requirement | Implementation and inspected evidence |
|---|---|
| Explicit independent policy | `output_policy.py`, production CLI/worker arguments, manifest/block/cohort controls; historical identity and mixed-policy comparison tests |
| Realistic onboard products, unchanged work | `pipeline.py`; native full-data field/selection/PNG equality; per-policy file inventories above; every full-profile image retained |
| Detailed acceptance kept separate | `full_validation.py` forces validation output; unchanged fifteen-gate contract; actual full local acceptance and post-exit artifact audit |
| Benchmark capabilities and raw observations retained | All performance manifests explicitly onboard; their other protocol settings unchanged; repeated fresh/persistent warmup/measured native tests; all observation levels; existing thermal/counter/scaling/duration/fault regressions passed |
| Policy-aware completion and historical reports | `onboard_validation.py`, `saved_attempts.py`, `validation_reference.py`, `experiment_report.py`, `comparison.py`, policy-aware image reader; damage/failure tests and actual historical import/report checks |
| Local verification and ordered documentation | 572-test XML; full-data verifier with actual storage inventories; installation → acceptance → pilot → performance → reporting workflow and handoff documents updated |

No Raspberry Pi was contacted, installed, deployed to or benchmarked for this
change. No network access, GitHub push, environment creation, `pip --user`, Pi
installer or dependency modification was performed. Existing archive/results,
old failed evidence and unrelated user files were preserved. New target
acceptance and hardware performance measurements remain later work. This audit
completes the local output-policy change, not the broader four-board benchmark
plan. Transfer/export-folder reorganization is outside this change.
