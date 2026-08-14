# PCS SUCHAI-1 post-processing

This repository rebuilds the SUCHAI-1 Langmuir-probe and particle-counter
post-processing pipeline as documented, testable Python code. The disorganized
`archive/` directory is read-only reference material and is not imported by the
new package.

The original SUCHAI telemetry is private and is not distributed by this
repository or its release bundles. Place an authorized local copy at
`data/raw/langmuir-2018-2.csv`; Git ignores that file. The public input manifest
keeps its checksum so authorized installations can verify the exact dataset.

The first working slice loads only trusted instrument products, assigns the
nearest historical TLE (including a later TLE when it is closer), propagates the
orbit through a selectable backend, and produces a minimal geographic
particle-count map. Previously calculated geographic and classification columns
in the source table are ignored.

AACGMv2 and ApexPy are both supported as first-class magnetic-coordinate
backends. They produce different native coordinate systems, so the edge-device
comparison emphasizes performance and reliability rather than numerical
equality. See `docs/magnetic-processing.md`.

## Local development first

All scientific logic is implemented and tested on the local development PC
before Raspberry Pi deployment. Raspberry Pis are used only for dependency
installation tests and controlled benchmarks after local validation.

```bash
python3 -m pip install -e ".[local]"
python3 -m pytest
pcsuchai analyze --orbit-backend astropy
pcsuchai analyze --orbit-backend astropy --magnetic-backend aacgmv2
pcsuchai analyze --orbit-backend astropy --magnetic-backend apexpy
```

Benchmark collection is opt-in:

```bash
pcsuchai analyze --orbit-backend astropy --benchmark
pcsuchai validate-orbits --limit 100
pcsuchai validate-magnetic --limit 100
```

See `docs/` for the hardware inventory and evolving scientific documentation.
The complete plot/filter profile and custom configuration schema are described
in `docs/plotting.md`; archive feature preservation is tracked explicitly in
`docs/archive-feature-parity.md`.

## Raspberry Pi operator workflow

The deployment path is automated and does not require activating a Python
environment or manually copying an ApexPy installation:

```bash
scripts/install_rpi.sh
scripts/run_quick_check.sh pi5
scripts/run_comparison.sh pi5
```

Use `scripts/run_full_products.sh` to benchmark every archive-parity image,
`scripts/run_stability.sh` for repeated thermal/memory testing, and
`scripts/run_endurance.sh` for resumable multi-day campaigns. Benchmark storage
is UTC-ordered by device/year/month/day/session; every execution retains its
timestamped products, run record, and telemetry. Nothing is automatically
deleted. Installation,
experiment controls, artifact layout, and metric definitions are documented in
`docs/install/raspberry-pi.md`, `docs/running-benchmarks.md`, and
`docs/benchmark-metrics.md`.

Official campaigns first execute `scripts/run_full_validation.sh` semantics and
require a certificate matching the exact source, inputs, interpreter,
dependencies, and full 32-plot workload. The acceptance contract is defined in
`docs/full-code-validation.md`. Limited quick checks and focused component
benchmarks are explicitly marked non-official.

For redistribution, `scripts/create_release_bundle.sh` creates a single
checksum-protected archive and includes any architecture-specific ApexPy wheels
previously cached by the installer.
