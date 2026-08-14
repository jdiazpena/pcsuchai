#!/usr/bin/env bash
# Install PCS SUCHAI and all native/scientific dependencies for the current Pi.
# No virtual-environment activation is used and pip is never run with sudo.

set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
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

if ((INSTALL_APT)); then
    sudo apt-get update
    sudo apt-get install -y \
        python3-pip python3-dev gfortran build-essential pkg-config ninja-build \
        patch curl ca-certificates libopenblas-dev liblapack-dev
fi

PIP_ARGS=(--user --break-system-packages)
"$PYTHON_BIN" -m pip install "${PIP_ARGS[@]}" --upgrade pip setuptools wheel meson meson-python ninja
"$PYTHON_BIN" -m pip install "${PIP_ARGS[@]}" --requirement requirements/rpi-common.txt

MACHINE=$($PYTHON_BIN -c 'import platform; print(platform.machine())')
PY_TAG=$($PYTHON_BIN -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')
WHEEL_DIR="$ROOT_DIR/vendor/wheels/${MACHINE}-${PY_TAG}"
SOURCE_DIR="$ROOT_DIR/vendor/sources"
mkdir -p "$WHEEL_DIR" "$SOURCE_DIR"

APEX_WHEEL=$(find "$WHEEL_DIR" -maxdepth 1 -type f -name "apexpy-2.1.1-${PY_TAG}-${PY_TAG}-*.whl" -print -quit)
if [[ -z "$APEX_WHEEL" ]]; then
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
    FC=/usr/bin/gfortran CC=/usr/bin/gcc "$PYTHON_BIN" -m pip wheel \
      --wheel-dir "$WHEEL_DIR" --no-deps "$BUILD_DIR/apexpy-2.1.1"
    APEX_WHEEL=$(find "$WHEEL_DIR" -maxdepth 1 -type f -name "apexpy-2.1.1-${PY_TAG}-${PY_TAG}-*.whl" -print -quit)
fi

if [[ -z "$APEX_WHEEL" ]]; then
    printf 'ERROR: ApexPy build completed without a compatible wheel.\n' >&2
    exit 4
fi

"$PYTHON_BIN" -m pip install "${PIP_ARGS[@]}" --force-reinstall --no-deps "$APEX_WHEEL"
"$PYTHON_BIN" -m pip install "${PIP_ARGS[@]}" --no-deps "$ROOT_DIR"

"$PYTHON_BIN" - <<'PY'
import numpy as np
from apexpy import Apex

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

"$PYTHON_BIN" -m pcsuchai capabilities
REPORT_DIR="$ROOT_DIR/installation-reports"
mkdir -p "$REPORT_DIR"
"$PYTHON_BIN" -m pcsuchai installation-report \
  --apex-wheel "$APEX_WHEEL" \
  --output "$REPORT_DIR/${MACHINE}-${PY_TAG}.json"
printf '\nInstallation complete. Run: scripts/run_quick_check.sh DEVICE_LABEL\n'
