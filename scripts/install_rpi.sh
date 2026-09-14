#!/usr/bin/env bash
# Install PCS SUCHAI and all native/scientific dependencies for the current Pi.
# Global installation for Debian's standard Python; no virtual environments.

set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=/usr/bin/python3
INSTALL_APT=1
OFFLINE=0

usage() {
    printf '%s\n' \
      'Usage: scripts/install_rpi.sh [--no-apt] [--offline]' \
      '' \
      '  --no-apt   Skip Debian package installation (use when already installed).' \
      '  --offline  Require an ApexPy wheel already cached under vendor/wheels.'
}

while (($#)); do
    case "$1" in
        --no-apt) INSTALL_APT=0 ;;
        --offline) OFFLINE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

cd "$ROOT_DIR"

if [[ $(uname -s) != Linux ]]; then
    printf 'ERROR: this installer is for Raspberry Pi Linux.\n' >&2
    exit 2
fi

PYTHON_BIN=$(command -v "$PYTHON_BIN")
# Tools installed globally must also be found by unprivileged native builds.
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
INSTALL_STAMP=$(date -u +%Y%m%dT%H%M%S.%NZ)
REPORT_DIR="$ROOT_DIR/installation-reports/$INSTALL_STAMP"
mkdir -p "$REPORT_DIR"
exec > >(tee "$REPORT_DIR/install.log") 2>&1
INSTALL_STAGE='prerequisites'
trap 'status=$?; printf "ERROR: installation failed during %s (exit %s). Full log: %s/install.log\n" "$INSTALL_STAGE" "$status" "$REPORT_DIR" >&2; exit "$status"' ERR
printf 'Installing globally with %s. Logs: %s\n' "$PYTHON_BIN" "$REPORT_DIR"

# Record the ordinary user's existing packages before changing anything. The
# previous --user installer may have left packages here; do not delete them.
"$PYTHON_BIN" - "$REPORT_DIR/before-packages.json" <<'PY'
import json
import sys
from importlib.metadata import distributions
from pathlib import Path

records = [
    {"name": dist.metadata.get("Name"), "version": dist.version,
     "location": str(dist.locate_file(""))}
    for dist in distributions()
]
Path(sys.argv[1]).write_text(json.dumps(records, indent=2) + "\n")
PY

# Use system Python's global packages, not custom Python search paths. Every
# build/check below uses -s to ignore legacy user-site copies; no environment
# is created or activated, and no existing user packages are deleted.
unset PYTHONPATH PYTHONUSERBASE VIRTUAL_ENV

printf '1/3: Installing required system libraries and Python dependencies.\n'
if ((INSTALL_APT)); then
    sudo apt-get update
    sudo apt-get install -y \
        python3-pip python3-dev gfortran build-essential pkg-config ninja-build \
        patch curl ca-certificates libopenblas-dev liblapack-dev
fi

GLOBAL_PYTHON=(sudo -H "$PYTHON_BIN" -s)

global_pip_install() {
    # Normal global installation: retain packages that satisfy requirements.
    # --isolated ignores per-user pip configuration; it creates no environment.
    "${GLOBAL_PYTHON[@]}" -m pip --isolated install \
        --break-system-packages "$@"
}

INSTALL_STAGE='global build tools'
global_pip_install --report "$REPORT_DIR/pip-build-tools.json" \
    'setuptools>=77' wheel meson meson-python ninja
INSTALL_STAGE='global scientific dependencies'
global_pip_install --report "$REPORT_DIR/pip-scientific.json" \
    --requirement requirements/rpi-common.txt

printf '2/3: Installing ApexPy with the proven ARM build fix.\n'
MACHINE=$("$PYTHON_BIN" -s -c 'import platform; print(platform.machine())')
PY_TAG=$("$PYTHON_BIN" -s -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')
WHEEL_DIR="$ROOT_DIR/vendor/wheels/${MACHINE}-${PY_TAG}"
SOURCE_DIR="$ROOT_DIR/vendor/sources"
mkdir -p "$WHEEL_DIR" "$SOURCE_DIR"

APEX_WHEEL=$(find "$WHEEL_DIR" -maxdepth 1 -type f -name "apexpy-2.1.1-${PY_TAG}-${PY_TAG}-*.whl" -print -quit)
if [[ -z "$APEX_WHEEL" ]]; then
    INSTALL_STAGE='ApexPy source download, patch and native wheel build'
    if ((OFFLINE)); then
        printf 'ERROR: no compatible cached ApexPy wheel in %s\n' "$WHEEL_DIR" >&2
        exit 3
    fi
    APEX_ARCHIVE="$SOURCE_DIR/apexpy-2.1.1.tar.gz"
    if [[ ! -f "$APEX_ARCHIVE" ]]; then
        curl -fL --retry 3 \
          -o "$APEX_ARCHIVE" \
          'https://files.pythonhosted.org/packages/d1/87/052779ac4c12588d286331e6029af9b43be3d3f18a65cbd3d07933775144/apexpy-2.1.1.tar.gz'
    fi
    printf '%s  %s\n' \
      'f1f0a555664f75734a02bb48217676b5534e40eb0e8d64e04bf24274be7f7825' \
      "$APEX_ARCHIVE" | sha256sum --check

    BUILD_DIR=$(mktemp -d)
    cleanup() { rm -rf -- "$BUILD_DIR"; }
    trap cleanup EXIT
    tar -xzf "$APEX_ARCHIVE" -C "$BUILD_DIR"
    patch -d "$BUILD_DIR/apexpy-2.1.1" -p1 < packaging/apexpy-2.1.1-optional-quadmath.patch
    FC=/usr/bin/gfortran CC=/usr/bin/gcc "$PYTHON_BIN" -s -m pip --isolated wheel \
      --wheel-dir "$WHEEL_DIR" --no-deps --no-build-isolation "$BUILD_DIR/apexpy-2.1.1"
    APEX_WHEEL=$(find "$WHEEL_DIR" -maxdepth 1 -type f -name "apexpy-2.1.1-${PY_TAG}-${PY_TAG}-*.whl" -print -quit)
fi

if [[ -z "$APEX_WHEEL" ]]; then
    printf 'ERROR: ApexPy build completed without a compatible wheel.\n' >&2
    exit 4
fi

INSTALL_STAGE='global ApexPy installation'
global_pip_install --report "$REPORT_DIR/pip-apexpy.json" --no-deps "$APEX_WHEEL"
INSTALL_STAGE='global PCS SUCHAI installation'
global_pip_install --report "$REPORT_DIR/pip-pcsuchai.json" --no-deps --no-build-isolation "$ROOT_DIR"

printf '3/3: Verifying SUCHAI runtime dependencies and backend imports.\n'
INSTALL_STAGE='SUCHAI dependency versions and compatibility checks'
"$PYTHON_BIN" -s scripts/check_dependencies.py \
    --policy requirements/rpi-version-policy.txt \
    --report "$REPORT_DIR/dependencies.json"

INSTALL_STAGE='backend imports and ApexPy conversion check'
"$PYTHON_BIN" -s - <<'PY'
import importlib
import numpy as np
from apexpy import Apex

for module in ("numpy", "matplotlib", "astropy", "sgp4", "skyfield",
               "aacgmv2", "apexpy", "psutil", "pcsuchai"):
    importlib.import_module(module)
    print(f"Import PASS: {module}")

apex = Apex(date=2018.5)
lat = np.array([-60.0, -30.0, 0.0, 30.0, 60.0])
lon = np.array([-120.0, -60.0, 0.0, 60.0, 120.0])
qlat, qlon = apex.convert(lat, lon, "geo", "qd", height=300.0)
back_lat, back_lon = apex.convert(qlat, qlon, "qd", "geo", height=300.0, precision=1e-10)
lat_error = float(np.max(np.abs(back_lat - lat)))
lon_error = float(np.max(np.abs((back_lon - lon + 180.0) % 360.0 - 180.0)))
assert np.isfinite(qlat).all() and np.isfinite(qlon).all()
assert lat_error < 1e-4 and lon_error < 1e-4
print(f"ApexPy round-trip PASS: latitude={lat_error:.3e} deg longitude={lon_error:.3e} deg")
PY

INSTALL_STAGE='capabilities and native dependency report'
"$PYTHON_BIN" -s -m pcsuchai capabilities
"$PYTHON_BIN" -s -m pcsuchai installation-report \
  --apex-wheel "$APEX_WHEEL" \
  --output "$REPORT_DIR/native-${MACHINE}-${PY_TAG}.json"
printf '\nInstallation complete. Run: scripts/run_quick_check.sh DEVICE_LABEL\n'
