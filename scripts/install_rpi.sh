#!/usr/bin/env bash
# Install PCS SUCHAI and all native/scientific dependencies for the current Pi.
# Global installation for Debian's standard Python; no virtual environments.

set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/usr/bin/python3}
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

# This dependency belongs to an existing typing package, not PCS SUCHAI. Only
# request its repair when that package actually declares it and it is missing.
STUB_REQUIREMENT=$("$PYTHON_BIN" - <<'PY'
from importlib.metadata import PackageNotFoundError, distribution

try:
    existing = distribution("types-seaborn")
except PackageNotFoundError:
    existing = None
if existing is not None:
    try:
        distribution("pandas-stubs")
    except PackageNotFoundError:
        for requirement in existing.requires or ():
            if requirement.lower().replace("_", "-").startswith("pandas-stubs"):
                print(requirement)
                break
PY
)

# Ignore old ~/.local packages throughout installation/native build. This does
# not create an environment or remove those packages; it selects global ones.
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONUSERBASE VIRTUAL_ENV

if ((INSTALL_APT)); then
    sudo apt-get update
    sudo apt-get install -y \
        python3-pip python3-dev gfortran build-essential pkg-config ninja-build \
        patch curl ca-certificates libopenblas-dev liblapack-dev
fi

# Use the OS Python, never the earlier user-installed pip. Null config prevents
# a pip setting from silently redirecting this operation back to --user/target.
GLOBAL_PYTHON=(sudo -H env -u PYTHONPATH -u PYTHONUSERBASE -u VIRTUAL_ENV
    "PATH=$PATH" PYTHONNOUSERSITE=1 PIP_CONFIG_FILE=/dev/null "$PYTHON_BIN" -s)
INSTALL_STAGE='global installation destination check'
"${GLOBAL_PYTHON[@]}" - <<'PY'
import sys
from pathlib import Path
from pip._internal.locations import get_scheme

if sys.prefix != sys.base_prefix or Path(sys.base_prefix).resolve() != Path("/usr"):
    raise SystemExit("Use Debian's /usr/bin/python3, not a virtual environment or Conda Python.")
scheme = get_scheme("pcsuchai", isolated=True)
# Debian's compiler include path remains /usr/include; package libraries,
# commands and data must use the administrator's /usr/local destinations.
for name in ("purelib", "platlib", "scripts", "data"):
    path = Path(getattr(scheme, name)).resolve()
    if not path.is_relative_to(Path("/usr/local")):
        raise SystemExit(f"Unsafe global pip destination for {name}: {path}; refusing to write OS-managed directories.")
print(f"Global Python libraries: {scheme.purelib}\nGlobal commands: {scheme.scripts}")
PY

global_pip_install() {
    # --ignore-installed prevents pip uninstalling Debian-owned dependencies.
    # New files go only to the verified /usr/local scheme. Do not upgrade pip
    # itself: the apt-managed pip remains the installer used here.
    "${GLOBAL_PYTHON[@]}" -m pip --isolated install \
        --break-system-packages --ignore-installed --root-user-action=ignore "$@"
}

INSTALL_STAGE='global build tools'
global_pip_install --report "$REPORT_DIR/pip-build-tools.json" \
    setuptools wheel meson meson-python ninja
INSTALL_STAGE='global scientific dependencies'
global_pip_install --report "$REPORT_DIR/pip-scientific.json" \
    --requirement requirements/rpi-common.txt
if [[ -n "$STUB_REQUIREMENT" ]]; then
    INSTALL_STAGE='repair of existing types-seaborn dependency'
    printf 'Repairing the missing dependency declared by types-seaborn: %s\n' "$STUB_REQUIREMENT"
    global_pip_install --report "$REPORT_DIR/pip-typing-repair.json" \
        --constraint requirements/rpi-common.txt "$STUB_REQUIREMENT"
fi

MACHINE=$($PYTHON_BIN -c 'import platform; print(platform.machine())')
PY_TAG=$($PYTHON_BIN -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')
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

INSTALL_STAGE='global package versions and ApexPy import/conversion checks'
"$PYTHON_BIN" -s - <<'PY'
import numpy as np
from apexpy import Apex
from importlib.metadata import distribution
from pathlib import Path

for line in Path("requirements/rpi-version-policy.txt").read_text().splitlines():
    requirement = line.split("#", 1)[0].strip()
    if not requirement:
        continue
    name, expected = requirement.split("==", 1)
    installed = distribution(name)
    location = Path(installed.locate_file("")).resolve()
    if installed.version != expected or not location.is_relative_to(Path("/usr/local")):
        raise SystemExit(f"Invalid global package {name}: {installed.version} at {location}; expected {expected} under /usr/local")
    print(f"Global package PASS: {name}=={expected} at {location}")

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

INSTALL_STAGE='dependency consistency checks'
"$PYTHON_BIN" -s -m pip check > "$REPORT_DIR/pip-check-global.txt" 2>&1 || {
    cat "$REPORT_DIR/pip-check-global.txt"
    printf 'ERROR: global dependencies are inconsistent; see %s/install.log\n' "$REPORT_DIR" >&2
    exit 5
}
# Also check what normal interactive Python sees, including legacy user extras.
# Do not label a dependency-conflicted login installation as complete.
env -u PYTHONNOUSERSITE "$PYTHON_BIN" -m pip check > "$REPORT_DIR/pip-check-login.txt" 2>&1 || {
    cat "$REPORT_DIR/pip-check-login.txt"
    printf 'ERROR: login-user dependencies are inconsistent; see %s/install.log\n' "$REPORT_DIR" >&2
    exit 5
}
cat "$REPORT_DIR/pip-check-global.txt" "$REPORT_DIR/pip-check-login.txt"
INSTALL_STAGE='capabilities and native dependency report'
"$PYTHON_BIN" -s -m pcsuchai capabilities
"$PYTHON_BIN" -s -m pcsuchai installation-report \
  --apex-wheel "$APEX_WHEEL" \
  --output "$REPORT_DIR/native-${MACHINE}-${PY_TAG}.json"
printf '\nInstallation complete. Run: scripts/run_quick_check.sh DEVICE_LABEL\n'
