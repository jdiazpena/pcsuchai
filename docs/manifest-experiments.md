# Manifest-driven experiments

This launcher executes the complete scientific pipeline for every job. It
supports seven version-1 protocols under `configs/experiments/`: acceptance,
equal-work, sustained, persistent, counters, scaling and observation overhead.
Implementation of the entire completion plan is still in progress; these
commands do not imply that every board or analysis deliverable is certified.

The [local operator matrix](local-operator-validation.md) records short native
foreground execution of all seven protocol kinds and the stress variant, with
explicit diagnostic adaptations and real unavailable-sensor/counter outcomes.

Run from `pcsuchai`. Use the already installed interpreter: system `python3`
on a Pi, the existing Miniconda `python3` on this local PC. The launcher disables
user-site shadowing before project imports using the same interpreter; it
does not activate/create an environment or install/change Python.

## Start and inspect

After the documented Pi installation, the acceptance command is:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/acceptance.json --device-label pi5
```

It performs one 100-row job through each of the four backend pairs, using the
three default maps. After successful smoke jobs, it performs the complete
26,725-row, 32-configured-plot scientific validation. Acceptance is intentionally
not a thermally controlled performance comparison. Selected optional backends
can be omitted in a separate diagnostic manifest; requiring the full
certificate still requires the complete validation backend matrix.
After the full-data validation, the launcher checks every saved smoke attempt
against that full reference and records the detailed decisions under
`acceptance/<segment>/`. A failed/incomplete scientific decision prevents root
completion. These checks and their saved wall/CPU costs are outside measured
job clocks; they do not consume a duration block's requested time.

Equal work uses three independent sessions and ten scheduled attempts per pair
per session. The proposed thermal gate needs calibration with each board's
built-in temperature trace before freezing a comparative protocol:

```bash
python3 scripts/run_experiment.py run --manifest configs/experiments/equal-work.json --device-label pi5 --detach
```

The printed `EXPERIMENT:` directory is the handle for all subsequent commands.
Replace `EXPERIMENT_DIRECTORY` below with that exact path:

```bash
python3 scripts/run_experiment.py status EXPERIMENT_DIRECTORY
python3 scripts/run_experiment.py stop EXPERIMENT_DIRECTORY
python3 scripts/run_experiment.py resume EXPERIMENT_DIRECTORY --detach
```

Detached jobs run on the Pi after closing SSH, not on the notebook. The launch
log and segment identity are retained. They do not survive reboot as running
processes: resume is explicit. Status checks boot ID, PID and kernel process
start time, so stale metadata/PID reuse is not mistaken for a live job. During
a long block, committed counts come from its live atomic checkpoint.

Run/resume and report/export/import also retain dated whole-operation cost
receipts, separate from immutable scientific payloads and per-job timing.
See [whole-operation-costs.md](whole-operation-costs.md) for exact scopes,
optional external command timing/raw stdout/stderr and the `costs` audit command.

Stop requests finish the active complete job and stop before another job or
recovery period. SIGINT/SIGTERM follow the same policy. Thermal recovery checks
the request at the configured sensor cadence. A full acceptance validation is
not interrupted mid-scientific check; its outputs are retained. Old stop files
belong to old segments and are never erased by resume.

One inherited device lock excludes overlapping experiments, validations and
profilers on a Pi. Do not delete the lock file to bypass it. A readiness
observation timeout prints the actual child handle: inspect that handle/log;
do not launch another copy just because observation timed out.

## Freeze the intended work

Version-1 manifests reject unknown fields and contradictory settings. Copy and
edit a protocol *before* starting it; each new experiment stores its immutable
effective manifest. No stopping-rule override is accepted during resume.

For a four-hour single-pair sustained test, in a copy of `sustained.json`, set
`workload.pairs` to one desired pair, for example `["skyfield-apexpy"]`, and
`execution.stop.value` to `14400`. Its stop kind remains
`duration_per_pair_seconds`. With all four pairs selected, four hours means
four hours **per pair**, not four hours total. Pair blocks recover before the
next block, not between jobs within a sustained block.

For comparable work across devices, use `attempts_per_pair` and the same
frozen count, row selection, plotting profile and source/library versions.
An attempt is scheduled work, not a target number of successful runs. Failures
and interruptions consume slots. Warm-ups are separate; there are no automatic
retries. Duration begins after the block's validation, initial thermal gate and
warm-ups and ends after the active job, without forcing another round.

Persistent mode uses one production worker per block/segment. It recomputes
measurements, TLE selection, orbit, magnetic conversion and plots each time;
only imports/library caches remain alive. This is distinct from OS warmed-file
cache state. Neither mode drops caches or changes governors/firmware policy.
Both one-thread and stock thread policies are explicit; effective native
library-thread provenance remains part of the completion audit.

Observation levels control worker instrumentation, not scientific output:
`minimal` keeps external timing but no stage sampler; `normal` adds stage/raw
telemetry; `detailed` adds lower-rate native thread/map snapshots. Each preserves
all acquired raw observations. Independent supervisor/board observations still
operate in every level. Measure overhead rather than subtracting an assumed
constant. Hardware counter probes save permission/support/coverage evidence;
unavailable counters remain unavailable, not zero, and software timing proceeds.

A small scaling selection can legitimately leave a requested day/night,
geographic, count or time filter empty. The program preserves that unchanged
filter, writes its complete raw mask and saves an annotated `empty_selection`
image at the requested dimensions. It does not silently remove the image or
invent observations, a colour range, selected times or a centroid. A centroid
without usable positive finite particle weight is explicitly unavailable.

## Records and abrupt termination

The root contains `manifest.json`, `experiment-state.json`, compressed input
snapshots, a source snapshot and immutable `segments/<UTC>/` control records.
Work lives under `sessions/session-<N>/block-<N>-<variant>/`. Each block retains
its checkpoint, append-only events, complete raw board timeline, worker protocol
and dated `runs/YYYY-MM-DD/<UTC>-r<round>-<pair>/` directories.

Every started attempt first commits `attempt-intent.json`. Its original
terminal `run-record.json`, raw arrays, PNGs, masks, logs and samples remain
available. Resume scans attempts omitted by a checkpoint after abrupt exit.
Verified terminal successes are recovered without another execution. Partial
slots are classified interrupted; damaged terminal records are classified
failed. An immutable `reconciliation-record.json` records that decision without
rewriting/deleting the original bytes. Unknown/duplicate slot identities fail
closed instead of silently choosing a replacement. Missing cycle-commit timing
remains unavailable, never reconstructed as invented elapsed time.
Gracefully stopped duration experiments retain their committed duration clock.
After abrupt exit with uncommitted elapsed time, resume recovers the records but
does not launch more timed work under an unknowable remaining-duration budget;
start a new dated experiment if further timed work is wanted.

Raw journals flush each row and fsync at most one second apart plus finalization;
JSON commits fsync the file before atomic replacement. This is not a promise
of zero loss after power failure. Recovery verifies committed artifacts and
preserves recoverable partial files. Keep sufficient storage headroom for one
large job: between-job free-space checks alone cannot guarantee it fits.

The developer-only [local recovery check](local-recovery-validation.md) runs
real native jobs and injects SIGKILL into its own supervisor, then verifies
fixed/timed resume, immutable orphan bytes and outcome-aware saved reports.
It is not a Pi benchmark or a replacement for target/full-data acceptance.

## Lossless transfer and verification

Stop/wait for the verified live handle to exit before exporting. Export creates
a new archive outside the experiment, preserving all raw, failed and partial
files and empty attempt folders, not just summaries:

```bash
python3 scripts/run_experiment.py export EXPERIMENT_DIRECTORY --output outputs/pi5-experiment.tar.gz
```

Save the printed SHA-256 alongside the archive. After transferring it to the
analysis PC, import into a **new** directory (replace `TRANSFER_SHA256`):

```bash
python3 scripts/run_experiment.py import outputs/pi5-experiment.tar.gz outputs/imported-pi5-experiment --sha256 TRANSFER_SHA256
python3 scripts/run_experiment.py verify-import outputs/imported-pi5-experiment
python3 scripts/run_experiment.py verify-import outputs/imported-pi5-experiment --images
```

Import rejects traversal, symlinks, devices, unknown/duplicate members and
unsafe hard links. It checks every original file's size/hash and the complete
inventory, including failures and partial CSV/JSON. Existing destinations and
archives are not overwritten. Failed imports leave their new partial directory
for inspection; choose another new directory for a subsequent attempt.

Original JSON bytes and hashes remain unchanged. `PortablePaths` resolves
internal recorded absolute/relative references against the imported root;
external original input names remain provenance, with compressed snapshots
retained internally. Historic plain-log references can resolve to their verified
gzip. Successful byte verification is not scientific agreement, target
acceptance or authorization to resume a different device/runtime.
`--images` additionally decodes the images declared by retained analysis
manifests, checks dimensions/counts/geographic context against their raw masks,
and resolves all image references inside the imported directory. It does not
rerun any orbit/magnetic backend or certify partial attempts without manifests.

## Reconstruct reports

After transfer, use the saved-record reporter on the analysis PC:

```bash
python3 scripts/run_experiment.py report outputs/imported-pi5-experiment --output outputs/reports/pi5-first
```

It reads all dated attempts, verifies snapshots/products/filter decisions,
preserves failure accounting, and supports multiple independent sessions on
one board. The report is still diagnostic, not whole-plan acceptance. See
[saved-benchmark-reports.md](saved-benchmark-reports.md) for the exact cohort,
uncertainty, raw-journal, plotting and exclusion contracts.
