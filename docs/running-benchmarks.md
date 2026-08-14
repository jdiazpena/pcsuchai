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
| Multi-day endurance | `scripts/run_endurance.sh pi5 72 "case open"` | Full workload continuously for at least 72 active hours, finishing the current four-scenario round |

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
5. Randomizes scenario order using a recorded seed.
6. Validates required artifacts and hashes derived scientific CSV files across
   identical repeats.
7. Atomically maintains `benchmark-session.checkpoint.json` throughout a long
   campaign and supports exact-workload resume.
8. Appends and flushes timestamped events and system telemetry while the
   campaign is running.
9. Writes complete JSON plus flat CSV reports.
10. Never deletes benchmark products. A free-space guard stops the campaign
    before the SD card is filled.

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
    ├── run-timeseries.csv
    ├── stage-timeseries.csv
    ├── scenario-summary.csv
    ├── warmups/
    ├── runs/
    │   └── YYYY-MM-DD/
    │       └── <UTC>-r<round>-<orbit>-<magnetic>/
    │           ├── run-record.json
    │           ├── system-telemetry.csv
    │           └── products/
    └── perf/
```

`run-timeseries.csv` is the easiest file for studying total runtime,
temperature, available RAM, CPU frequency, throttling, and output size across
repeats. `stage-timeseries.csv` contains the same sequence broken down into
loading, TLE selection, orbit propagation, magnetic conversion, CSV writing,
and each plot. `scenario-summary.csv` contains mean, median, population
standard deviation, minimum, maximum, and interpolated 95th percentile.

`system-telemetry.csv` is the continuous UTC timeline. By default it is flushed
every two seconds and records the active run identifier, phase, SoC
temperature, CPU frequency and utilization, available/used memory, swap, load,
and free storage. The matching per-run telemetry file is stored beside that
run's products. `heartbeat.json` always contains the newest complete sample.
`campaign-events.jsonl` is append-only and records starts, completions, failures,
resumes, and the final stop reason.

Every run identifier begins with a microsecond-resolution UTC timestamp. No
run-directory cleanup, rotation, overwrite, or automatic artifact deletion is
implemented. Failed and interrupted run directories are evidence and must also
be retained. Only the atomic checkpoint and current heartbeat replace their
own previous versions; the append-only event and telemetry journals preserve
the history.

## Multi-day endurance operation

Run the declared three-day profile with:

```bash
scripts/run_endurance.sh pi5
```

Override the duration in hours without editing the profile:

```bash
scripts/run_endurance.sh pi5 120 "five-day run, active cooler"
```

Duration is measured as active campaign time and checked between complete
randomized rounds. A round contains all four Astropy/Skyfield × AACGMv2/ApexPy
scenarios, so the campaign can exceed the requested duration by one round. It
always attempts at least two rounds so variance and repeat consistency remain
defined.

The endurance profile has no cooldown, keeps every generated product, samples
system telemetry every two seconds, stops at 80 °C between executions, stops
with 2 GB free storage remaining, records individual failures, and stops after
three consecutive failures. These stops do not delete or overwrite anything.

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
- `warmups`: discarded warm-up rounds;
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
