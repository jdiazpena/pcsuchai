# Thermal reports from retained software measurements

Use only the Pi's existing built-in SoC sensor and saved firmware/software
observations. No external temperature sensor, power meter, energy measurement
or extra hardware is part of this workflow. Run reporting after the experiment
has stopped, preferably on the analysis PC with its existing Python.

```bash
python3 scripts/run_experiment.py report EXPERIMENT_DIRECTORY --output outputs/reports/thermal-first
```

The report includes `thermal_analysis` in `experiment-report.json`, all original
observations in `observations.jsonl.gz`, every complete/partial thermal window
in `thermal-windows.jsonl.gz`, observed firmware changes in
`throttle-transitions.jsonl.gz`, and `thermal-*.png`. No raw data is pruned.
These plots/reporting costs are outside the satellite-style worker timings.

## Temperature windows and heating

Temperature groups preserve experiment, block, segment, source, scope and unit.
Only available finite Celsius readings with original monotonic acquisition
times can qualify a window. Initial/peak/final **sampled** readings, means,
observed span, acquisition gaps and least-squares heating slopes remain visible.
Phase summaries distinguish saved idle/warm-up/measured contexts. Context
labels are not atomic timestamps of every independently acquired reading's
worker/stage boundary. Sampled extrema can miss brief peaks.

The version-1 exploratory analysis defaults are:

- A window spanning at least 300 actual acquisition seconds and three readings.
- Absolute temperature slope no greater than 0.2 Celsius degrees/minute.
- Sampled maximum-minus-minimum temperature no greater than 2 Celsius degrees.
- No intervening unavailable/malformed reading, clock regression or acquisition
  gap greater than 1.5 times the frozen requested board-sampling interval.
- At least two consecutive qualifying windows.

Windows close on observed span, not a nominal time bin inferred from row count
or UTC timestamps. One closing boundary reading is shared with the next window;
it remains one original acquisition in total/phase counts. Online centred
regression/endpoints/extrema use constant memory. Every emitted window is
streamed to disk, including short final windows, outages and failed criteria.

Candidate plateau classification applies only to declared continuous
single-pair sustained/persistent blocks. It starts after the first measured
context; idle retention between those jobs is part of the block. An idle
baseline alone and a thermally recovered equal-work protocol cannot establish
a sustained-work plateau. A qualifying observation in a stopped/damaged block
is explicitly labelled **partial block evidence**, not sustained acceptance.
The status describes candidate windows observed somewhere in the saved series,
not a guarantee that the final temperature remains stationary.

These are explicit **exploratory report criteria**, not pilot-calibrated sensor
limits, confidence intervals, firmware protection settings or proof of physical
equilibrium. A time trend or temperature/latency association does not establish
causal thermal dependence. Actual per-board pilot traces must determine whether
the window/range/slope/gap criteria suit the sensor cadence/resolution.

To apply different declared report criteria without modifying the original
benchmark's frozen protocol or records:

```bash
python3 scripts/run_experiment.py report EXPERIMENT_DIRECTORY --output outputs/reports/thermal-longer --thermal-window-seconds 600 --thermal-maximum-slope-c-per-minute 0.2 --thermal-maximum-range-c 2 --thermal-maximum-gap-factor 1.5 --thermal-consecutive-windows 2
```

The effective analysis policy is saved in the report. Changing these report
parameters does not change the benchmark stopping rule or thermal start gate.

## Current versus historical firmware flags

The decoder uses Raspberry Pi's
[documented `get_throttled` bit identities](https://www.raspberrypi.com/documentation/computers/os.html#get_throttled).
Current bits 0–3 and historical bits 16–19 are separate tracks/counts. A
historical condition already present at the first sample is not a newly
observed event or a current condition. Unknown bits are retained uninterpreted.

New campaign journals acquire `vcgencmd get_throttled` once per board sample
and reuse that result in the structured observation and legacy hexadecimal
column. Every structured mask retains unit, scope, source, availability,
UTC and monotonic acquisition time. Missing/denied/malformed responses are
not zero. Legacy journals lacking individual mask acquisition times can still
have their recorded masks decoded, but cannot supply a timed transition or
exposure duration. The reporter never queries firmware on the analysis PC.

Transition records retain both sampled endpoint states, actual acquisition gap,
newly set/cleared current bits, newly observed historical bits and historical
clearance anomalies. Large gaps/clock anomalies remain explicit. Changes are
bracketed between samples; exact onset, cause and continuous active duration
are unavailable. In particular, a throttling bit does not by itself uniquely
identify temperature as the cause. An undervoltage flag is not a measurement
of voltage, power or energy.

Each segment has a separate derived thermal figure. Acquisitions use the
retained segment elapsed anchor where available. Older timed readings without
an anchor stay on their explicitly labelled absolute monotonic clock; no UTC
subtraction invents a segment anchor. Display envelopes retain first/last/min/
max samples with bounded plotting memory while preserving all original data.
