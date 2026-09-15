# Magnetic reference acceptance

Full-code validation contract version 2 adds two required gates, one for each
magnetic backend. They run outside measured attempts alongside orbit acceptance;
they do not split the main satellite-style processing chain into separate jobs.
Normal production runs still import only the selected optional backend.

`src/pcsuchai/assets/magnetic-reference-cases.json` freezes the inputs, expected
values, units, upstream version/source and tolerances. Installation includes this
asset. Validation never downloads expected values or regenerates them from the
current installation. Updating a model/version requires reviewing and freezing
new model-specific references, not widening tolerances until a test passes.

## What the cases prove

| Check | Frozen cases | Interpretation |
|---|---|---|
| AACGMv2 2.7.0 published regression | Eight forward/inverse coefficient/tracing conversions at two UTC epochs; one high-altitude ALLOWTRACE case; three inverse-MLT cases including negative and greater-than-24-hour inputs | Installed public APIs reproduce published upstream numerical results |
| ApexPy 2.1.1 published regression | Two direct geographic/modified-apex conversions and five height mappings, including conjugate, same-height and high-altitude cases; decimal epoch 2000 and reference height 300 km | Installed coordinate/mapping primitives reproduce the published upstream regression |
| Production API bridge, each model | Two epochs, both geographic dateline representations on a leap day, invalid-orbit propagation; additional AACGM equatorial undefined and high-altitude fallback cases | Our actual factory returns the same coordinates, MLT and geographic projection as explicit native primitive calls with production settings; every field/mask/unit is checked |

Published upstream regressions are **not independent physical truth**. ApexPy's
[pinned upstream tests](https://raw.githubusercontent.com/aburrell/apexpy/v2.1.1/apexpy/tests/test_Apex.py)
explicitly describe their hard-coded values as regression results obtained from
the tested code, expected to change when IGRF changes. Our bridge is also
explicitly a same-native-library check, not another independent model.
Neither source proves absolute magnetic accuracy, field-line accuracy against
observations, or cross-device floating-point tolerances. Those limits are part
of the saved report, not just this documentation.

AACGM values and four-decimal precision come from the
[pinned C-wrapper tests](https://raw.githubusercontent.com/aburrell/aacgmv2/v2.7.0/aacgmv2/tests/test_c_aacgmv2.py).
We retain the upstream strict absolute bound `abs(delta) < 1.5e-4`, with each
component in its own unit, following
[NumPy's documented decimal comparison](https://numpy.org/doc/stable/reference/generated/numpy.testing.assert_almost_equal.html).
Apex mappings retain upstream `atol=1e-5, rtol=1e-5`. Printed example digits
are not an accuracy promise. Bridge comparisons use their separately frozen
`atol=1e-7, rtol=0` plumbing bound; this is not a model-accuracy budget.

## Frames and projection settings

Bridge inputs are WGS84 geodetic latitude/longitude in degrees and ellipsoidal
altitude in kilometres; timestamps are timezone-aware UTC, including seconds.
Apex's published cases intentionally use reference height 300 km, while the
production bridge uses the production reference height 0 km and its actual
observation epoch. Those are different, explicitly recorded checks.

Apex's geographic footpoint targets **zero geodetic altitude** and returns an
angular mapping residual in degrees. AACGM's inverse targets **zero model
height on its 6371.2-km reference sphere** and returns geodetic altitude in km,
not an angular residual. That altitude is retained; the unavailable angular
residual stays null/NaN. These model-specific projections must not be equated
or relabelled as identical physical field-line tracing. See
[magnetic processing](magnetic-processing.md).

For every bridge, the actual production output is retained in native units
and re-audited for row lengths, finite/invalid masks, coordinate definitions,
longitude/MLT ranges and model-specific altitude/residual semantics. Invalid
orbit rows retain error code 2 and unavailable coordinate fields; AACGM's
undefined equatorial row retains error code 1, not a fake zero location.

The bridge uses `geo2apex`/`mlon2mlt` for Apex and
`convert_latlon`/`convert_mlt` for AACGM, rather than calling the same combined
`convert`/`get_aacgm_coord` wrappers as production. Local injected-wrapper
fault tests require the published primitive anchors to remain passing while
the production bridge fails. This checks dispatch plumbing within the same
library; it does not turn that library into an independent physical oracle.

## Retained evidence and historical reports

Run the existing complete validator; no extra installation command is needed:

```bash
scripts/run_full_validation.sh DEVICE_LABEL
```

Direct API calls must also use a new directory. Existing complete or partial
validation artifact directories are rejected before reading inputs or changing
any retained product; compressed reference outputs are created exclusively.
A failed reservation stays recoverable and is not silently reused or removed.

Its dated validation directory includes:

- `magnetic/reference-cases/aacgmv2.json.gz`;
- `magnetic/reference-cases/apexpy.json.gz`;
- the complete `full-validation-certificate.json` with fifteen required gates
  instead of the previous thirteen (additional optional SYM-H remains separate).

Compressed reports retain every acquired anchor/bridge value, expected values,
deltas, units, exact case definitions, installed version, and hashes/paths/sizes
of installed native binaries and configured coefficient files. Failed cases
stay in the report. A missing library, unexpected model version, failed case or
missing/changed report cannot establish acceptance. The certificate hashes both
reports and the executable source identity includes the frozen case asset.
Acquired outputs also retain exact little-endian IEEE float64 bytes as hex,
including NaN, infinity and signed zero; nullable JSON is only presentation,
not a replacement for the original numeric bits.

Readers verify retained report bytes and replay fixed numerical bounds from
the experiment's archived case asset, without importing or executing archived
code. Bridge values remain explicitly same-library results. Stored invariant
flags are rechecked against raw bridge values, rather than accepted on faith.
Hashes detect retained corruption, not authentication of malicious self-signed
archives or proof of physical accuracy.

Old certificates are not erased or retroactively declared version 2. A verified
archived source without either new reference source member retains its original
thirteen-gate contract. Either new source member requires version 2, both gates
and both reports. Removing a version flag or the new criteria cannot downgrade
new-source acceptance to the historical contract. Active execution additionally
requires the exact current source/runtime/inputs as before.

Local native references do not certify the four Pis. Per-board dependency/ABI,
coefficient, numerical and capability acceptance still needs actual saved Pi
results; no extra equipment or external sensor is required.
