# Raspberry Pi installation for operators

This is the operator installation procedure. It starts from a clean Raspberry
Pi OS Lite / Debian 13 machine and requires no Python-environment activation.
The older `APEXPY_RPI5_ARM64_INSTALL.md` is the engineering record that led to
the automated installer; operators should not reproduce those manual steps.

## Supported targets

| Device | OS / architecture | Expected status |
|---|---|---|
| Pi 5 | Debian 13, 64-bit `aarch64` | Reference ApexPy build already demonstrated |
| Pi 4 | Debian 13, 64-bit `aarch64` | Reuses the same wheel when Python ABI matches |
| Pi Zero 2 W | Debian 13, 64-bit `aarch64` | Reuses the same wheel when Python ABI matches |
| Pi Zero W | Raspbian 13, 32-bit `armv6l` | Requires its own native wheel; installation remains to be proven |

A wheel may only be reused when both the architecture and Python tag match.
The installer enforces this through separate directories such as
`vendor/wheels/aarch64-cp313` and `vendor/wheels/armv6l-cp313`.

## Connected installation

Clone the repository, which now includes the canonical CSV, TLE and EOP data:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/jdiazpena/pcsuchai.git
```

Then run:

```bash
cd pcsuchai
scripts/install_rpi.sh
python3 scripts/run_experiment.py run --manifest configs/experiments/acceptance.json --device-label pi5
```

The maintainer may distribute one checksum-protected archive instead of a Git
checkout:

```bash
scripts/create_release_bundle.sh
```

This requires Git and clean committed tracked files. It writes
`dist/pcsuchai-<version>-<commit-prefix>.tar.gz` and a matching `.sha256` file,
refusing to replace either existing artifact. Untracked local material is never
packaged; accidentally committed private/generated paths are rejected. It
includes code, documentation, the canonical measurement CSV, TLE/EOP inputs, configuration, and compatible
cached wheels while excluding the read-only archive, old outputs, Git metadata,
installation reports, alternative raw files, secrets/configuration and source
caches. `release-manifest.json` binds every source/wheel byte to a Git commit.
Cached wheels are checked for matching Apex version and filename/directory/WHEEL
tags, not executed; runtime/native/full-data acceptance is still mandatory.
Publication uses Linux hard links; use a destination supporting them. A failed
publication retains its new partial files for diagnosis. No retained benchmark
data are removed. See [Pi 5 handoff](../pi5-handoff.md) for exact first-run commands.

The installer:

1. installs Debian compilers and native prerequisites;
2. installs the pinned Python dependencies globally under `/usr/local`;
3. downloads ApexPy 2.1.1 and verifies its published SHA-256 digest;
4. applies `packaging/apexpy-2.1.1-optional-quadmath.patch` automatically;
5. builds and caches a native wheel for the current architecture/Python ABI;
6. installs PCS SUCHAI;
7. checks the pinned SUCHAI packages and their active runtime dependencies;
8. imports every backend, performs an Apex geographic/QD round trip and records native-library dependencies.

It writes a timestamped directory `installation-reports/<UTC>/` with a complete
`install.log`, a before-install package inventory, per-step pip JSON reports,
`dependencies.json` and `native-<architecture>-<python-tag>.json` with the
cached wheel hash, installed native-extension hash, dynamic-library inspection,
interpreter, and scientific package versions. A missing shared library makes
that report fail.

Run the script as the ordinary `pi` user, without putting `sudo` before the
script: it invokes `sudo` internally for apt and global Python installation.
It uses Debian's `/usr/bin/python3`. There is no virtual environment
and no `pip --user`. Python commands are installed under `/usr/local/bin`,
which the installer puts on its PATH before building anything.

Global installation uses system Python with `sudo` and
`--break-system-packages`. Already-installed packages satisfying the
requirements are reused: there is no forced reinstall, `--ignore-installed`,
or pip upgrade. The installer invokes pip with `--isolated` only to ignore
per-user pip configuration; that option does not create a Python environment.
Global packages can replace or shadow OS-provided versions, so this workflow
is intended for the dedicated benchmark machines.

## Recovering from the older per-user installer

If an older installation is still running, interrupt it with Ctrl+C, then
update the repository and rerun the installer:

```bash
git pull --ff-only
scripts/install_rpi.sh
```

The new installer leaves existing `~/.local` packages, data, results and cached
wheels in place. Installation/build processes and benchmark-master children
disable Python's user-site lookup so old user packages do not shadow the
global installation; this is a startup setting, not a virtual
environment. Normal interactive Python may still see those older packages.

Dependency verification is restricted to the pinned packages in
`requirements/rpi-version-policy.txt` and their recursively required runtime
packages. `scripts/check_dependencies.py` checks installed versions, Python
compatibility and active platform/extra requirements, writing
`dependencies.json`. A missing or incompatible SUCHAI dependency stops the
installer before success is printed. Backend imports and the Apex round trip
are also required to pass.

The installer does not run whole-system `pip check` and does not repair or
install unrelated packages such as Flask, tree-sitter or pandas-stubs. Pip may
still print warnings about unrelated pre-existing packages; those warnings
are not an installation failure unless a SUCHAI dependency is affected. Old
installation reports, results, user packages and cached wheels are retained.

The Astropy pin is `7.2.2`: Astropy `7.1.x` references `numpy.in1d`, removed
in NumPy `2.4`. The NumPy `2.5.2` and ApexPy `2.1.1` reference versions are
unchanged. Installation and preflight import `astropy.units`, coordinates,
time and IERS, plus `skyfield.api` and `sgp4.api`, rather than only importing
their top-level packages. This catches runtime incompatibilities before a
measured analysis starts. The upstream Astropy fix is visible in its
[quantity helper implementation](https://github.com/astropy/astropy/blob/v7.2.2/astropy/units/quantity_helper/function_helpers.py).

If the Debian prerequisites are already installed:

```bash
scripts/install_rpi.sh --no-apt
```

## Reusing ApexPy without rebuilding

Run the connected installer once on the Pi 5. It leaves the working native
wheel inside the repository under `vendor/wheels/aarch64-cp313/` (the exact
Python tag may differ). Preserve that wheel when distributing the repository.
On another ABI-compatible 64-bit Pi, the installer detects and uses it.

For a machine without Internet access:

```bash
scripts/install_rpi.sh --offline
```

Offline mode currently requires the ApexPy wheel to be cached, but the other
pinned Python packages must also already be installed or supplied by a future
complete wheelhouse. Do not copy `/home/pi/.venvs/apexpy` or a `site-packages`
directory: those contain absolute paths and ABI-specific files and are not a
reproducible deployment artifact.

## Installation acceptance

Installation checks alone are not scientific acceptance. Run the unified
acceptance command above. Require a successful exit, root
`experiment-state.json` with `"status": "complete"`, all four smoke attempts
accepted against their own full-data references, and a passing fifteen-gate
`full-validation-certificate.json`. Preserve the entire printed experiment
directory. A stopped, failed or partial campaign is not acceptance.
The older quick campaign remains a diagnostic, not a replacement for this gate.

The installer itself is deliberately tested on each Pi as dependency work.
Scientific source code is not edited or debugged on a Pi. Any scientific or
pipeline failure is reproduced and fixed on the local development PC first.

After unified acceptance and pilot review, use the single-pair four-hour
commands in [Pi 5 handoff](../pi5-handoff.md). The older mixed-pair launcher
remains available as a separate legacy workload; for example:

```bash
python3 scripts/run_detached.py pi5 24
```

Use `48` instead of `24` for two days. The launcher prints a log path and PID;
follow that log to see preflight, full validation, the campaign directory and
progress. Closing SSH does not stop it. A failed preflight stops before
measurement. The existing 2 GB free-space guard may end a campaign before its
requested duration; it never deletes earlier results.

Raw samples and input snapshots are losslessly compressed, and identical
repeated products share backing storage on the normal Linux filesystem. See
[raw-data retention](../raw-data-retention.md) for reading, exporting and
preserving these data. Record the actual existing cooling configuration; this
example neither requires nor assumes a particular cooler.

## Updating dependencies

Do not casually run an unpinned `pip install --upgrade`. Edit the pins under
`requirements/`, validate the complete pipeline locally, install the same pins
on every Pi, and begin a new benchmark series. Results from different package
sets must not be merged as if they were one experiment.
