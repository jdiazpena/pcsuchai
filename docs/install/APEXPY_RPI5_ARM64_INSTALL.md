
# Installing ApexPy on Raspberry Pi 5 / Debian ARM64

> Engineering record: this documents the original manual experiment. New
> operators should use `scripts/install_rpi.sh` and
> `docs/install/raspberry-pi.md`; they should not recreate or copy this virtual
> environment by hand.

## Purpose

This document records a successful ApexPy installation on a Raspberry Pi 5,
explains why the normal source build failed, shows the exact local workaround,
and proposes a more portable upstream fix.

It is intended to be usable both as:

- a standalone installation guide for Raspberry Pi OS or Debian on ARM64; and
- the technical basis for an ApexPy GitHub issue or pull request.

## Result

ApexPy 2.1.1 was built successfully as a native CPython 3.13 ARM64 extension:

```text
apexpy-2.1.1-cp313-cp313-linux_aarch64.whl
```

The installed environment is:

```text
/home/pi/.venvs/apexpy
```

The installation passed import, conversion, dynamic-link, and numerical
round-trip checks.

## Test system

The installation documented here used:

```text
Hardware:       Raspberry Pi 5
Architecture:   aarch64 (64-bit ARM)
Operating OS:   Debian GNU/Linux 13 (trixie), Raspberry Pi repositories enabled
Python:         CPython 3.13.5
GCC:            14.2.0
GNU Fortran:    14.2.0
ApexPy:         2.1.1
NumPy:          2.5.2
```

Check a different machine with:

```bash
uname -m
cat /etc/os-release
python3 --version
gcc --version | head -n 1
gfortran --version | head -n 1
```

The workaround is relevant when `uname -m` reports `aarch64` (or possibly an
ARM variant) and the ApexPy build ends with `cannot find -lquadmath`.

## The original failure

The documented ApexPy source installation was attempted after installing a C
compiler, GNU Fortran, Python headers, Meson/Ninja support, and a virtual
environment. Compilation itself succeeded. The final shared-library link failed:

```text
[15/15] Linking target fortranapex.cpython-313-aarch64-linux-gnu.so
FAILED: fortranapex.cpython-313-aarch64-linux-gnu.so
...
-lm -lquadmath lib_fortranobject.a -lgfortran
/usr/bin/ld: cannot find -lquadmath: No such file or directory
collect2: error: ld returned 1 exit status
ninja: build stopped: subcommand failed.
```

This matters diagnostically: the compiler and the ApexPy Fortran sources were
working. Failure occurred only when the linker was explicitly instructed to
link `libquadmath`.

## Root cause

ApexPy 2.1.1 contains this unconditional line in `meson.build`:

```meson
add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
```

That forces every target platform to provide a linkable `libquadmath`, whether
the generated ApexPy extension actually requires that library or not.

On Debian 13 ARM64, no native `libquadmath0` package is available. Debian's
package page lists the native package for `amd64`, `i386`, and `ppc64el`, but
not `arm64`. This is also observable locally:

```bash
apt-cache policy libquadmath0
gcc -print-file-name=libquadmath.so
```

On the tested Pi those commands show no package candidate and return the bare
name `libquadmath.so`, respectively. Returning only the bare name means GCC did
not resolve the library to an installed path.

By contrast, GNU Fortran's normal runtime is present:

```bash
gfortran -print-file-name=libgfortran.so
```

Output on the tested Pi:

```text
/usr/lib/gcc/aarch64-linux-gnu/14/libgfortran.so
```

## What `libquadmath` is, and whether it is critical

`libquadmath` is GCC's quad-precision math library. It provides mathematical
functions for the GNU `__float128` type and, on targets that use it, support
for GNU Fortran `REAL(16)` operations.

It is **not the normal GNU Fortran runtime**. That runtime is `libgfortran`,
which remains installed and linked.

For this ApexPy build, `libquadmath` is not critical:

1. A source search found no use of `REAL(16)`, `real128`, `__float128`,
   `quadmath`, or `selected_real_kind` requesting quad precision.
2. ApexPy's explicit higher-precision declarations are `REAL(8)`, which are
   double precision, not quad precision.
3. Removing the forced `-lquadmath` argument allowed the complete source to
   compile and link.
4. The resulting module imports and performs real Apex coordinate conversions.
5. Numerical round-trip tests pass to better than `8e-6` degrees.
6. ELF inspection shows no unresolved or runtime dependency on `libquadmath`.

The installed extension's direct dynamic dependencies were:

```text
libm.so.6
libgfortran.so.5
libc.so.6
libgcc_s.so.1
```

Therefore, this workaround does **not** remove ApexPy's required Fortran
runtime. It only removes an unavailable, unused, explicitly forced library.

One should not generalize this to arbitrary Fortran projects. A project that
uses `REAL(16)` or calls quadmath APIs may genuinely need quad-precision
support. The conclusion here is based on ApexPy's source and a working tested
binary.

## Exact installation procedure used

### 1. Install system build prerequisites

```bash
sudo apt-get update
sudo apt-get install -y \
  python3-pip \
  python3-venv \
  python3-dev \
  gfortran \
  build-essential \
  pkg-config \
  ninja-build
```

Why these are needed:

- `python3-venv`: creates an isolated Python environment;
- `python3-pip`: installs Python packages;
- `python3-dev`: supplies `Python.h` and other extension-building headers;
- `gfortran`: compiles ApexPy's Fortran implementation and supplies
  `libgfortran`;
- `build-essential`: supplies GCC, the linker, and standard native build tools;
- `pkg-config`: helps Meson locate development dependencies;
- `ninja-build`: runs the Meson-generated build.

### 2. Create an isolated environment

```bash
mkdir -p /home/pi/.venvs
python3 -m venv /home/pi/.venvs/apexpy
/home/pi/.venvs/apexpy/bin/python -m pip install --upgrade pip setuptools wheel
```

Using a virtual environment avoids Debian's externally-managed-system-Python
restrictions and prevents scientific package versions from changing OS tools.

To use a different location, replace every occurrence of
`/home/pi/.venvs/apexpy` below.

### 3. Download the exact ApexPy 2.1.1 source archive

```bash
mkdir -p /home/pi/src/apexpy-build
curl -fsSL \
  -o /home/pi/src/apexpy-build/apexpy-2.1.1.tar.gz \
  https://files.pythonhosted.org/packages/d1/87/052779ac4c12588d286331e6029af9b43be3d3f18a65cbd3d07933775144/apexpy-2.1.1.tar.gz
```

Verify the published SHA-256 checksum before extracting:

```bash
printf '%s  %s\n' \
  'f1f0a555664f75734a02bb48217676b5534e40eb0e8d64e04bf24274be7f7825' \
  '/home/pi/src/apexpy-build/apexpy-2.1.1.tar.gz' \
  | sha256sum --check
```

Expected output:

```text
/home/pi/src/apexpy-build/apexpy-2.1.1.tar.gz: OK
```

Extract it:

```bash
tar -xzf /home/pi/src/apexpy-build/apexpy-2.1.1.tar.gz \
  -C /home/pi/src/apexpy-build
```

### 4. Apply the exact local patch used on this Pi

Open:

```text
/home/pi/src/apexpy-build/apexpy-2.1.1/meson.build
```

Replace:

```meson
add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
```

with:

```meson
# Debian arm64's GCC does not ship libquadmath. ApexPy does not use
# REAL(16), so linking this optional GNU runtime is unnecessary here.
if host_machine.cpu_family() not in ['aarch64', 'arm']
  add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
endif
```

Or apply it non-interactively from the extracted source directory:

```bash
cd /home/pi/src/apexpy-build/apexpy-2.1.1
patch -p1 <<'PATCH'
--- a/meson.build
+++ b/meson.build
@@ -68,1 +68,6 @@
-add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
+# Debian arm64's GCC does not ship libquadmath. ApexPy does not use
+# REAL(16), so linking this optional runtime is unnecessary here.
+if host_machine.cpu_family() not in ['aarch64', 'arm']
+  add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
+endif
PATCH
```

This is the exact type of conditional patch used for the successful local
build. See the later upstream proposal for a more general implementation.

### 5. Build and install

```bash
FC=/usr/bin/gfortran CC=/usr/bin/gcc \
  /home/pi/.venvs/apexpy/bin/python -m pip install \
  /home/pi/src/apexpy-build/apexpy-2.1.1
```

Setting `FC` and `CC` is not always necessary, but makes the selected native
compilers unambiguous.

Successful output includes something similar to:

```text
Successfully built apexpy
Successfully installed apexpy-2.1.1 numpy-2.5.2
```

## Verification

### Basic import

```bash
/home/pi/.venvs/apexpy/bin/python -c \
  "import apexpy; print(apexpy.__version__, apexpy.__file__)"
```

Expected version:

```text
2.1.1
```

### Functional round-trip test

```bash
/home/pi/.venvs/apexpy/bin/python - <<'PY'
import numpy as np
from apexpy import Apex

a = Apex(date=2026.0)
glat = np.array([-60., -30., 0., 30., 60.])
glon = np.array([-120., -60., 0., 60., 120.])

qlat, qlon = a.convert(glat, glon, 'geo', 'qd', height=300.)
back_lat, back_lon = a.convert(
    qlat, qlon, 'qd', 'geo', height=300., precision=1e-10
)

lat_error = np.max(np.abs(back_lat - glat))
lon_error = np.max(np.abs((back_lon - glon + 180.) % 360. - 180.))

print(f'Max latitude round-trip error:  {lat_error:.3e} deg')
print(f'Max longitude round-trip error: {lon_error:.3e} deg')

assert np.isfinite(qlat).all() and np.isfinite(qlon).all()
assert lat_error < 1e-4
assert lon_error < 1e-4
print('SELF-TEST: PASS')
PY
```

Observed on the tested Pi:

```text
Max latitude round-trip error:  3.815e-06 deg
Max longitude round-trip error: 7.629e-06 deg
SELF-TEST: PASS
```

Do not require exact equality with old coordinate values copied from ApexPy's
documentation. ApexPy 2.1.1 includes updated IGRF coefficient data, so tiny
differences from examples generated with an older data revision are expected.
A round-trip test is a better installation check.

### Inspect dynamic dependencies

```bash
find /home/pi/.venvs/apexpy \
  -name 'fortranapex*.so' \
  -exec ldd {} \;
```

There should be no `not found` entries. On this Pi, the extension loads
`libgfortran.so.5` and does not request `libquadmath`.

For a machine-readable ELF view:

```bash
readelf -d \
  /home/pi/.venvs/apexpy/lib/python3.13/site-packages/apexpy/fortranapex*.so \
  | grep NEEDED
```

## Using the installation

Activate the environment in an interactive shell:

```bash
source /home/pi/.venvs/apexpy/bin/activate
python -c "from apexpy import Apex; print(Apex(date=2026.0))"
```

Run scripts either after activation:

```bash
python your_script.py
```

or without activation, using the environment's interpreter explicitly:

```bash
/home/pi/.venvs/apexpy/bin/python your_script.py
```

Leave the activated environment with:

```bash
deactivate
```

## Recommended upstream fix

The CPU-name conditional fixed this specific Raspberry Pi installation, but
feature detection is more robust than an architecture list. Availability can
vary with operating system, compiler, target ABI, and future toolchains.

The best upstream direction is to stop adding raw `-lquadmath`
unconditionally. Since current ApexPy does not use quad precision, the simplest
fix may be to remove the line entirely:

```diff
-add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
```

If maintainers want to retain it for toolchains where it is useful, Meson
should probe for it:

```meson
quadmath_dep = fc.find_library('quadmath', required: false)

fortran_deps = [py3_dep, fortranobject_dep]
if quadmath_dep.found()
  fortran_deps += quadmath_dep
endif
```

Then use `fortran_deps` for the extension's `dependencies`:

```meson
py3.extension_module('fortranapex',
  # existing sources and other arguments...
  dependencies: fortran_deps,
  subdir: 'apexpy',
  install: true)
```

An even stricter variant is to make `libquadmath` required only after a build
test demonstrates that the compiler or source actually needs a quadmath
symbol. For the current source, no such requirement was found.

Why this is preferable:

- it lets Meson express and track a library dependency normally;
- it works on Debian ARM64 without maintaining a deny-list;
- it retains the dependency on targets that provide it;
- it avoids assuming that all AArch64 systems behave like Debian GNU/Linux;
- it produces a clearer configuration message than a final linker failure.

The project should add an ARM64 Linux CI job that builds the source distribution
and runs at least the import and round-trip tests above. Native ARM64 GitHub
Actions runners or an ARM64 container/runner would catch this regression.

## Suggested upstream issue text

The following can be pasted into an ApexPy GitHub issue and adjusted as needed:

> **Title: ApexPy 2.1.1 source build fails on Debian 13 ARM64 due to unconditional `-lquadmath`**
>
> I attempted to build ApexPy 2.1.1 from the PyPI source distribution on a
> Raspberry Pi 5 running Debian 13 (`aarch64`), CPython 3.13.5, GCC/GFortran
> 14.2.0, and NumPy 2.x. All Fortran and C objects compile, but the final link
> fails with:
>
> ```text
> /usr/bin/ld: cannot find -lquadmath: No such file or directory
> collect2: error: ld returned 1 exit status
> ```
>
> `meson.build` unconditionally calls:
>
> ```meson
> add_project_link_arguments('-lquadmath', language: ['c', 'fortran'])
> ```
>
> Debian trixie does not provide native `libquadmath0` for ARM64. The package is
> available only for selected architectures. ApexPy's Fortran source appears to
> use `REAL(8)`, not `REAL(16)`/`__float128`, so quadmath does not appear to be a
> functional requirement on this target.
>
> Making the argument conditional allowed a native
> `apexpy-2.1.1-cp313-cp313-linux_aarch64.whl` to build. The installed extension
> imports successfully, runs coordinate conversions, and passes geographic ->
> quasi-dipole -> geographic round trips with maximum error below `8e-6`
> degrees. `readelf`/`ldd` show normal dependencies on `libgfortran` and `libm`
> and no dependency on `libquadmath`.
>
> Would you accept a change that removes the unconditional link argument, or
> uses `fc.find_library('quadmath', required: false)` and only adds the
> dependency when found? An ARM64 Linux source-build CI job would also prevent
> this from recurring.

## Suggested pull-request summary

```text
Make libquadmath optional in Meson builds

ApexPy currently adds -lquadmath unconditionally. Debian ARM64 toolchains do
not provide libquadmath, causing the source build to fail at the final link even
though all ApexPy C and Fortran sources compile successfully.

Detect quadmath with the Fortran compiler and add it only when available.
ApexPy's current Fortran sources do not use REAL(16) or quadmath APIs, and an
ARM64 build without the forced link passes import and coordinate round-trip
tests while retaining its libgfortran dependency.
```

## Alternatives considered

### Installing `libquadmath0`

This is not a solution on the tested Debian ARM64 release because there is no
native package candidate. Cross-architecture packages such as
`libquadmath0-amd64-cross` contain libraries for another target and must not be
used to satisfy a native AArch64 Python extension.

### Creating a fake or manual `libquadmath.so` symlink

Do not do this. There is no compatible native library to point at, and linking
an ARM64 extension to an x86-64 library is impossible. A misleading symlink can
turn a clear build error into a confusing ABI or loader failure.

### Disabling or removing `libgfortran`

Do not do this. `libgfortran` is required by the compiled Fortran extension.
The working module explicitly depends on `libgfortran.so.5`.

### Installing into the system Python with `sudo pip`

Do not do this. Modern Debian protects its system Python environment, and
overwriting OS-managed Python packages can break system utilities. Use a
virtual environment.

### Using a non-ARM prebuilt wheel

Do not do this. Python extension wheels contain architecture-specific native
code. An `x86_64`, `amd64`, or macOS wheel cannot run on Raspberry Pi ARM64.

## References

- ApexPy installation documentation:
  <https://apexpy.readthedocs.io/en/latest/installation.html>
- ApexPy 2.1.1 on PyPI:
  <https://pypi.org/project/apexpy/2.1.1/>
- ApexPy source repository:
  <https://github.com/aburrell/apexpy>
- Debian trixie `libquadmath0` package and architectures:
  <https://packages.debian.org/trixie/libquadmath0>
- GCC `libquadmath` manual:
  <https://gcc.gnu.org/onlinedocs/libquadmath/>
- GCC discussion explaining that AArch64 Linux uses 128-bit `long double` and
  does not need libquadmath in the same way as targets whose C library lacks
  that support:
  <https://gcc.gnu.org/bugzilla/show_bug.cgi?id=96016>

## Short conclusion

The problem is an ApexPy build-system portability issue, not a defective Pi,
Python installation, or Fortran compiler. ApexPy 2.1.1 forces linkage to a
library that Debian ARM64 does not ship and that ApexPy does not use on this
target. Making `libquadmath` optional (preferably through Meson feature
detection) fixes the build while preserving the required `libgfortran`
runtime.
