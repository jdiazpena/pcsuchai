# Running benchmark campaigns

An operator normally chooses one master script and supplies only a
non-identifying device label. Run these commands from the repository root.

Every official scenario is one uninterrupted process:

```text
trusted measurements + TLE/EOP
             ↓
      orbit propagation
      (Astropy/Skyfield)
             ↓
     magnetic conversion
     (AACGMv2/ApexPy)
             ↓
 analysis + geographic/magnetic/footpoint plots + auditable tables
```

Stage timers observe boundaries inside that process; they do not split the
satellite workload or reuse one backend's result to make another scenario
artificially cheaper.

| Purpose | Command | Work performed |
|---|---|---|
| Installation check | `scripts/run_quick_check.sh pi5` | 100 rows, 2 repeats, all 4 backend combinations |
| Controlled comparison | `scripts/run_comparison.sh pi5` | Full data, 1 warm-up + 5 measured repeats, randomized order, thermal baseline |
| Complete image workload | `scripts/run_full_products.sh pi5` | Full data and all archive-parity plots, 3 measured repeats |
| Thermal/memory stability | `scripts/run_stability.sh pi5` | Full data, 20 measured repeats per backend combination, no cooldown |
| One-/two-day endurance | `scripts/run_endurance.sh pi5 24 "case open"` | Full workload for 24 measured hours (use 48 for two days), finishing the active job at the deadline |
| Disconnect-safe endurance | `python3 scripts/run_detached.py pi5 24 "case open"` | The same campaign, detached from SSH, with a persistent launch log |

The three official profiles automatically run and bind a full-code validation
certificate before measurement. They all execute the complete 32-plot profile.
The quick profile is deliberately non-official and uses only 100 rows.

Focused engineering diagnostics are deliberately separate from official
campaign results:

| Diagnostic | Command | Artifacts |
|---|---|---|
| Orbit parity | `scripts/run_orbit_diagnostic.sh 100` | Validation JSON, benchmark JSON, row-level differences CSV, log |
| Magnetic parity | `scripts/run_magnetic_diagnostic.sh astropy 100` | Validation JSON, benchmark JSON, row-level differences CSV, log |
| Repeated orbit timing | `scripts/run_orbit_benchmark.sh 5` | Randomized clean-process repeats, hashes, statistics, CSV, JSON |

These diagnostics explain individual stages. They are never substituted for
the complete end-to-end timing used to compare Raspberry Pis.

See `docs/full-code-validation.md` for the exact acceptance contract and the
conditions that invalidate a certificate.

Optional notes can be added as the second argument:

```bash
scripts/run_comparison.sh pi5 "official supply, active cooler, case open"
```

Do not include a person's name, IP address, password, or Wi-Fi details in the
label or notes.

## What every master script does

1. Creates a new UTC-stamped session under `device/YYYY/MM/DD`; it never mixes
   a new campaign into an old folder.
2. Runs preflight and stops immediately on missing backends, changed inputs,
   wrong versions, insufficient storage, or unwritable output.
3. Captures board, OS, kernel, CPU, memory, swap, storage, governor, clock,
   thermal, throttling, and Python details without network identifiers.
4. Starts every measurement in a clean Python process.
5. Uses recorded random or balanced order and declared numerical-library threads.
6. Validates required artifacts and hashes derived scientific CSV files across
   identical repeats.
7. Atomically maintains `benchmark-session.checkpoint.json` throughout a long
   campaign and supports exact-workload resume.
8. Appends and flushes timestamped events and system telemetry while the
   campaign is running.
9. Writes complete per-run JSON plus flat CSV reports and summary JSON. Compact
   checkpoint/session entries reference complete run records on disk.
10. Preserves benchmark products and checks free space between runs. This guard
    does not guarantee that one large job fits; reserve sufficient headroom.

The master and standalone validation/benchmark entry points share one device
lock across repositories. Concurrent launches fail immediately; subprocesses
inherit the same lock. Stale owner text after a crash is not a live lock.

The existing master accepts an explicit fixed-work override:

```bash
python3 scripts/run_campaign.py --config configs/benchmark/comparison.json --device-label pi5 --attempts-per-pair 10 --session-index 1
```

`--attempts-per-pair` and `--duration-hours` are mutually exclusive. Resume uses
the saved effective stopping rule/index and rejects overrides. Failures consume
scheduled attempts; interruptions are retained and not silently retried. Session
reports include started, valid, failed, interrupted and skipped counts.

Measured duration begins after warm-ups and recovery and includes processing,
retention and any later recovery. No additional rounds are forced at the deadline.
Mixed-pair endurance remains a different workload from a sustained single-pair
block. A singleton execution gives no estimate of repeat uncertainty.

A requested legacy temperature target now fails closed on a missing sensor or
timeout. Stable recovery is available through `benchmark-suite --thermal-policy`
or a legacy campaign's `thermal_policy` object. It measures an idle baseline,
requires a complete stable window and saves compressed raw recovery traces.
The proposed values require pilot calibration before freezing a comparison.

Versioned reference protocols are in `configs/experiments/`. Use the unified
`scripts/run_experiment.py` launcher for these manifests, not the legacy
`--config` runner. Foreground/detached, status, graceful stop and exact-workload
resume use the same frozen contract. See [manifest-experiments.md](manifest-experiments.md)
for commands, process/thermal semantics and verified lossless transfer.
Comparison/reporting and target-specific acceptance still require the evidence
listed in [benchmark-implementation-status.md](benchmark-implementation-status.md).

## Session layout

```text
outputs/benchmarks/<device>/<YYYY>/<MM>/<DD>/<UTC>-<profile>/
├── campaign-config.json
├── command.json
├── preflight.json
├── preflight.log
├── hardware-and-os.txt
├── campaign.log
└── benchmark/
    ├── benchmark-session.checkpoint.json
    ├── benchmark-session.json
    ├── campaign-events.jsonl
    ├── heartbeat.json
    ├── system-telemetry.csv
    ├── system-telemetry.<segment-UTC>.csv.gz
    ├── inputs/
    ├── input-snapshots.json
    ├── source-snapshot.tar.gz
    ├── artifact-store/
    ├── run-timeseries.csv
    ├── stage-timeseries.csv
    ├── scenario-summary.csv
    ├── warmups/
    ├── runs/
    │   └── YYYY-MM-DD/
    │       └── <UTC>-r<round>-<orbit>-<magnetic>/
    │           ├── run-record.json
    │           ├── system-telemetry.csv.gz
    │           ├── stdout.log.gz
    │           ├── stderr.log.gz
    │           └── products/
    │               ├── raw-products-<backends>.npz
    │               ├── benchmark-<backends>.samples.csv.gz
    │               ├── <plot>.selection.npz
    │               └── CSVs, PNGs, benchmark summaries and manifest
    └── perf/
```

`run-timeseries.csv` is the easiest file for studying total runtime,
temperature, available RAM, CPU frequency, throttling, and output size across
repeats. `stage-timeseries.csv` contains the same sequence broken down into
loading, TLE selection, orbit propagation, magnetic conversion, CSV writing,
and each plot. `scenario-summary.csv` contains mean, median, population
standard deviation, minimum, maximum, and interpolated 95th percentile.

`system-telemetry.csv` is the live continuous UTC timeline. By default it is flushed
every two seconds and records the active run identifier, phase, SoC
temperature, CPU frequency and utilization, available/used memory, swap, load,
free storage and firmware throttling flags. Closed run timelines and closed
campaign segments are verified and gzip-compressed; no samples are discarded.
The matching per-run telemetry file is stored beside that run's products.
`heartbeat.json` always contains the newest complete sample.
`campaign-events.jsonl` is append-only and records starts, completions, failures,
resumes, and the final stop reason.

Every run identifier begins with a microsecond-resolution UTC timestamp. No
run-directory cleanup or pruning is implemented. Lossless compression replaces
closed plain raw journals only after verifying their decompressed checksum;
byte-identical completed products share storage without changing their paths.
Failed and interrupted run directories are evidence and must also
be retained. Only the atomic checkpoint and current heartbeat replace their
own previous versions; the append-only event and telemetry journals preserve
the history.

## Multi-day endurance operation

Run the declared one-day profile with:

```bash
scripts/run_endurance.sh pi5
```

Override the duration in hours without editing the profile:

```bash
scripts/run_endurance.sh pi5 48 "two-day run, active cooler"
```

Duration begins after initial recovery and warm-ups and is checked before
each complete attempt. The active job finishes at the deadline; no extra
rounds or minimum number of successes are forced. A round contains the four
selected pairs, but the deadline can end a partial round. A single completion
does not establish repeat uncertainty. New single-pair sustained blocks are
separate from this legacy mixed-pair workload.

The endurance profile has no cooldown, keeps every generated product, samples
system telemetry every two seconds, stops at 80 °C between executions, stops
with 2 GB free storage remaining, records individual failures, and stops after
three consecutive failures. These stops do not delete or overwrite anything.

For a campaign that survives closing SSH, use:

```bash
python3 scripts/run_detached.py pi5 24 "active cooler, case open"
```

The launcher prints a PID and persistent log path. Use the printed `tail -f`
command; the log prints `SESSION:` immediately with the campaign directory.
Detaching does not survive reboot/power loss; resume the recorded session
afterward with `scripts/resume_campaign.sh SESSION_DIRECTORY`. Effective
duration overrides are preserved on resume.

All acquired stage samples, trusted instrument arrays and configured plot
selections are retained, not only their summaries. Raw data use lossless gzip
or NPZ, and identical repeated scientific products are hard-linked within the
campaign to reduce physical storage consumption. See
`docs/raw-data-retention.md` for exact contents, interpretation and export.

Monitor it from another SSH session with:

```bash
tail -f outputs/benchmarks/pi5/YYYY/MM/DD/SESSION/benchmark/system-telemetry.csv
```

## Fair-comparison protocol

Use the same SD-card model, power supply, OS image, package pins, input files,
plot profile, cooling configuration, and CPU governor when the experimental
question is hardware performance. Record every intentional difference in the
notes. Reboot, allow background package updates to finish, and leave the Pi
idle before a controlled comparison.

The comparison profile waits at least 10 seconds and, on a Pi with a readable
thermal sensor, waits for 45 °C or up to 10 minutes between runs. The stability
profile deliberately disables cooldown so heat accumulation and throttling are
observable. These answer different questions; do not combine their timings.

Do not run compilation, desktop applications, updates, Codex, Node.js, or other
jobs during a measured campaign. They may remain installed, but active work
changes CPU load, memory availability, storage I/O, temperature, and scheduler
behavior.

## Custom campaigns

Copy one JSON file under `configs/benchmark/`, change its values, and run:

```bash
python3 scripts/run_campaign.py \
  --config configs/benchmark/my-test.json \
  --device-label pi4 \
  --notes "passive heatsink"
```

Available configuration keys are:

- `python_version`: exact interpreter version required for official runs;
- `orbit_backends`: any subset of `astropy`, `skyfield`;
- `magnetic_backends`: any subset of `aacgmv2`, `apexpy`;
- `repeats`: measured repetitions, minimum 2;
- `duration_hours`: active endurance duration; use `null` repeats for a
  duration-controlled campaign;
- `warmups`: retained warm-up rounds excluded from measured summaries;
- `limit`: first N observations, or `null` for all;
- `plot_config`: plot-profile path, or `null` for the three core maps;
- `seed`: deterministic scenario-order seed;
- `cooldown_seconds`: fixed delay after each process;
- `cooldown_until_c`: optional temperature target;
- `cooldown_max_seconds`: maximum thermal wait;
- `collect_perf`: request a separate Linux hardware-counter run;
- `timeout_seconds`: limit for each child process;
- `telemetry_interval_seconds`: continuous telemetry cadence;
- `minimum_free_gb`: stop threshold; products are never deleted to recover space;
- `maximum_temperature_c`: between-run thermal safety stop;
- `continue_on_error`: preserve a failed run and proceed to the next scenario;
- `max_consecutive_failures`: stop after this many successive failures.

`--allow-version-drift` exists only so the development PC can test orchestration
before adopting Pi pins. Never use it for a cross-device benchmark.

## Interrupted runs

An interruption leaves every completed product, the append-only journals, the
heartbeat, the latest atomic checkpoint, and any partial run directory. Do not
present a checkpoint as a complete benchmark and do not manually fill missing
runs.

Resume the exact session with:

```bash
scripts/resume_campaign.sh outputs/benchmarks/pi5/YYYY/MM/DD/SESSION
```

Resume is accepted only when the source digest, Python version, package
versions, inputs, settings, and backend matrix exactly match the checkpoint.
Completed run identifiers are skipped. A run that was active during abrupt
power loss is retained as a partial timestamped directory, and the replacement
attempt receives a new timestamp rather than overwriting it. Offline time is
not counted toward the requested active duration.

## Comparing completed devices

After copying completed session folders back to the development PC, combine
their final JSON reports with:

```bash
scripts/compare_devices.sh outputs/comparisons/official-01 \
  outputs/benchmarks/pi-zero-2/<session>/benchmark/benchmark-session.json \
  outputs/benchmarks/pi4/<session>/benchmark/benchmark-session.json \
  outputs/benchmarks/pi5/<session>/benchmark/benchmark-session.json
```

This creates `device-comparison.csv` only if every session is complete and has
matching source, inputs, Python version, package versions, settings, scenarios,
and repeat-consistent scientific outputs. Otherwise it creates a rejection
report listing every mismatch and exits nonzero. Absolute file paths are not
compared because they legitimately differ between machines.
## Representative workload selections

The analysis and benchmark-suite commands accept `--selection-method spread`
with `--limit N`. This keeps exactly N original observations, including the
first and last rows when N > 1, and recomputes the complete pipeline for them.
The raw NPZ retains the original source row IDs; the manifest records actual
time coverage and duplicate timestamps. Spread means source-index coverage,
not geographical or anomaly-stratified representativeness. A size larger than
the input fails. Existing prefix analysis retains its legacy capped-limit
behavior; prefix is intended for smoke tests. `--selection-method full` requires
no limit. With no limit, either prefix or spread also processes all rows.

Both fresh and persistent execution use the same selection function. The
legacy full-code certificate does not authorize a spread/scaling variant;
exact variant certification and the unified experiment launcher remain work
in progress. Do not label a non-official scaling diagnostic as a certified
cross-board benchmark.

## Persistent process lifetime

`benchmark-suite --process-mode persistent` starts one worker before recovery,
then invokes the same complete production analysis for each scheduled job.
Measurement tables, selected TLEs and magnetic converter objects are created
again for every job. Imports and normal library caches persist; the plotting
code also retains its existing cached Natural Earth context arrays. This is
not a cold-cache or cache-clearing experiment. Fresh remains the default.

The per-attempt external timer is a persistent request/response round trip,
including protocol persistence, rather than process launch through exit. The
worker response separately records science execution time. Worker startup/import
and shutdown have separate records, and worker/supervisor resource observations
remain raw. These differing boundaries must be declared when comparing process
lifetimes; do not treat the first-start cost as measured on every persistent
iteration. A timeout does not start a replacement or become a successful job.
Campaign finalization closes the actual worker and retains its protocol JSONL
and stderr as verified gzip plus `worker-exit.json`.

The short local tests check numerical parity, figure/descriptor cleanup and a
bounded RSS budget. They are not evidence of long-duration memory stability.
The complete persistent experiment/reporting workflow in the completion plan
is still being implemented.
