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

Transfer or clone the complete `pcsuchai` repository once, then run:

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
includes code, documentation, trusted data, configuration, and compatible
cached wheels while excluding the read-only archive, old outputs, Git metadata,
and caches.

The installer:

1. installs Debian compilers and native prerequisites;
2. installs the pinned Python dependencies for the current user;
3. downloads ApexPy 2.1.1 and verifies its published SHA-256 digest;
4. applies `packaging/apexpy-2.1.1-optional-quadmath.patch` automatically;
5. builds and caches a native wheel for the current architecture/Python ABI;
6. installs PCS SUCHAI;
7. performs an Apex geographic/QD round trip and reports all capabilities.

It also writes `installation-reports/<architecture>-<python-tag>.json` with the
cached wheel hash, installed native-extension hash, dynamic-library inspection,
interpreter, and scientific package versions. A missing shared library makes
that report fail.

It never runs `sudo pip`. Debian packages are installed with `sudo apt`, while
Python packages are placed in the login user's site directory. The
`--break-system-packages` flag is required by Debian's externally-managed
Python policy but, together with `--user`, does not overwrite Debian-owned
package files.

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

## Updating dependencies

Do not casually run an unpinned `pip install --upgrade`. Edit the pins under
`requirements/`, validate the complete pipeline locally, install the same pins
on every Pi, and begin a new benchmark series. Results from different package
sets must not be merged as if they were one experiment.
