# Magnetic-coordinate processing

PCS SUCHAI treats AACGMv2 and ApexPy as first-class, interchangeable onboard
processing backends. They consume the same recomputed WGS84 latitude,
longitude, altitude, and UTC observation time, but they do **not** produce the
same coordinate system:

- `aacgmv2` writes altitude-adjusted corrected geomagnetic (`aacgm`)
  latitude, longitude, and magnetic local time.
- `apexpy` writes modified-apex (`modified_apex`) latitude, longitude, and
  magnetic local time.

Every CSV and manifest records both the backend and coordinate-system name.
Numeric differences between them are diagnostic—not accuracy errors. Either
product can be interpreted or transformed after it is downloaded. The onboard
choice is therefore evaluated primarily by wall time, process CPU time, peak
resident memory, I/O, temperature, clock frequency, throttling, invalid-point
rate, image size, and table size.

Magnetic error codes are `0` for success, `1` when the model returns no finite
coordinate (AACGMv2 can be undefined near the magnetic equator), `2` when the
input orbit position is invalid, and `3` when the backend raises an error.

Both implementations also write a model-specific mapping to zero-kilometre
height. AACGMv2 performs an AACGM-to-geographic conversion at zero height;
ApexPy follows the field line with `map_to_height`. These are useful comparable
products, but are not asserted to be mathematically identical.

The height convention also differs: AACGM's inverse conversion at input
height zero targets its 6371.2 km geocentric reference sphere, then returns
geodetic coordinates and altitude. It does **not** necessarily return zero
geodetic altitude. This follows the
[AACGM 2.7.0 conversion implementation](https://github.com/aburrell/aacgmv2/blob/v2.7.0/c_aacgmv2/src/aacgmlib_v2.c#L901).
The returned altitude is retained as `surface_altitude_km` in raw arrays and
`surface_geodetic_altitude_km` in the CSV. ApexPy's target is zero geodetic
height. `mapping_error_deg` records ApexPy's angular mapping residual; it is
NaN (unavailable), not an altitude or a fabricated zero, for AACGMv2. Earlier
outputs incorrectly placed AACGM's altitude in that angular-error field.

Each production conversion now checks complete row lengths, explicit invalid
NaNs and error-code propagation, latitude/longitude ranges, MLT in `[0,24)`,
the backend's coordinate-system name, and its altitude/residual unit contract.
AACGM's returned altitude is checked against a generous reference-sphere
diagnostic bound; this is not a measure of mapping accuracy. These invariants
do not establish absolute model accuracy or equality between the two models.
Full-code validation additionally requires version-pinned upstream regression
cases and separately labelled production/native API bridges for each model.
All acquired values and numerical bits are retained; these are software
regressions, not independent physical truth. See
[magnetic reference acceptance](magnetic-reference-validation.md).

## Commands

Run one complete backend pipeline without benchmarking:

```bash
pcsuchai analyze --magnetic-backend aacgmv2
pcsuchai analyze --magnetic-backend apexpy
```

Add `--benchmark` to measure all processing and output stages consistently.
Run the focused, identical-input magnetic benchmark with:

```bash
pcsuchai validate-magnetic --limit 100
```

The timestamped master-script equivalent is:

```bash
scripts/run_magnetic_diagnostic.sh astropy 100
```

The diagnostic writes `magnetic-validation.json`, `magnetic-benchmark.json`,
`magnetic-differences.csv`, and `console.log`, matching the focused orbit
diagnostic artifact structure. The row-level CSV stores the common geographic
orbit input, both native magnetic results, both surface mappings, error codes,
and diagnostic native-coordinate differences. Those differences remain
differences between distinct models—not accuracy errors.

Increase or remove the limit only after this short dependency and correctness
check succeeds on the target machine.

Like the focused orbit diagnostic, this is an engineering explanation of one
stage. Official satellite-like results come from the complete backend
combination campaigns, which run orbit propagation and magnetic conversion
together in one process.
