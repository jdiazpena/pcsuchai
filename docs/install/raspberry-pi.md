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
scripts/run_quick_check.sh pi5
```

The maintainer may distribute one checksum-protected archive instead of a Git
checkout:

```bash
scripts/create_release_bundle.sh
```

This writes `dist/pcsuchai-<version>.tar.gz` and a matching `.sha256` file. It
includes code, documentation, the canonical measurement CSV, TLE/EOP inputs, configuration, and compatible
cached wheels while excluding the read-only archive, old outputs, Git metadata,
and caches.

The installer:

1. installs Debian compilers and native prerequisites;
2. installs the pinned Python dependencies globally under `/usr/local`;
3. downloads ApexPy 2.1.1 and verifies its published SHA-256 digest;
4. applies `packaging/apexpy-2.1.1-optional-quadmath.patch` automatically;
5. builds and caches a native wheel for the current architecture/Python ABI;
6. installs PCS SUCHAI;
7. verifies global package versions/locations and performs an Apex geographic/QD round trip;
8. checks both global and login-user dependency consistency before reporting success.

It writes a timestamped directory `installation-reports/<UTC>/` with a complete
`install.log`, a before-install package inventory, per-step pip JSON reports,
dependency-check output and `native-<architecture>-<python-tag>.json` with the
cached wheel hash, installed native-extension hash, dynamic-library inspection,
interpreter, and scientific package versions. A missing shared library makes
that report fail.

Run the script as the ordinary `pi` user, without putting `sudo` before the
script: it invokes `sudo` internally for apt and global Python installation.
It uses Debian's `/usr/bin/python3` by default. There is no virtual environment
and no `pip --user`. Python commands are installed under `/usr/local/bin`,
which the installer puts on its PATH before building anything.

Global pip operations use `--break-system-packages` because Debian marks its
Python externally managed. Before installation, the script verifies that pip's
library, command and data destinations are under `/usr/local`, not Debian-owned `/usr/lib`.
It uses `--ignore-installed` to avoid pip uninstalling existing Debian packages,
and does not upgrade pip itself. Global packages can still shadow OS-provided
versions, so this workflow is intended for the dedicated benchmark machines.
The relevant directory separation is described by the
[Python packaging specification](https://packaging.python.org/en/latest/specifications/externally-managed-environments/).

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
verified global installation; this is a startup setting, not a virtual
environment. Normal interactive Python may still see those older packages.

If an existing `types-seaborn` package declares a missing `pandas-stubs`
dependency, the installer repairs that dependency globally, constrained by the
scientific version pins. It does not install `types-seaborn` on a clean Pi or
remove unrelated packages. Any remaining dependency error stops installation
and is saved in `pip-check-global.txt` or `pip-check-login.txt`; success is never
printed just because `pip install` returned zero despite a conflict.

Dependency consistency is verified with
[`pip check`](https://pip.pypa.io/en/stable/cli/pip_check/).

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

The installation is accepted only after the quick campaign completes. Its
`preflight.json` must say `"status": "pass"`, and its final
`benchmark-session.json` must say both `"status": "complete"` and
`"scientific_outputs_consistent": true`.

The installer itself is deliberately tested on each Pi as dependency work.
Scientific source code is not edited or debugged on a Pi. Any scientific or
pipeline failure is reproduced and fixed on the local development PC first.

After the quick acceptance check, launch a disconnect-safe 24-hour campaign:

```bash
python3 scripts/run_detached.py pi5 24 "active cooler, case open"
```

Use `48` instead of `24` for two days. The launcher prints a log path and PID;
follow that log to see preflight, full validation, the campaign directory and
progress. Closing SSH does not stop it. A failed preflight stops before
measurement. The existing 2 GB free-space guard may end a campaign before its
requested duration; it never deletes earlier results.

Raw samples and input snapshots are losslessly compressed, and identical
repeated products share backing storage on the normal Linux filesystem. See
`docs/raw-data-retention.md` for reading, exporting and preserving these data.

## Updating dependencies

Do not casually run an unpinned `pip install --upgrade`. Edit the pins under
`requirements/`, validate the complete pipeline locally, install the same pins
on every Pi, and begin a new benchmark series. Results from different package
sets must not be merged as if they were one experiment.
