# Archive feature-parity contract

The `archive/` directory remains read-only reference material. PCS SUCHAI does
not import it, but the organized implementation must retain its scientific
capabilities before Raspberry Pi deployment begins.

## Coordinate and map products

- Spacecraft position in recomputed WGS84 geographic latitude and longitude.
- Native magnetic latitude and longitude from AACGMv2 or ApexPy.
- Magnetic field-line mapping back to zero-kilometre geographic latitude and
  longitude (the `footpoint` or `surface` map).
- Geographic maps include bundled land/continent outlines without Cartopy or a
  runtime network download.
- SAA particle-count centroids may be calculated in geographic, native
  magnetic, or surface/footpoint coordinates.

## Measurements available for colour mapping

All trusted source measurements remain available, not only particle count:

- particle count;
- plasma temperature;
- plasma voltage;
- sweep voltage;
- plasma current;
- electron density at 300 K;
- electron density at 3000 K.

Electron density may use the archive-compatible base-10 logarithmic colour
scale. Every variable may also use explicitly selected linear or logarithmic
scaling.

## Filters

Filters are composable and use the same implementation for plotting and
centroid/statistical analysis:

- one or more included UTC time intervals;
- one or more excluded UTC time intervals;
- minimum and maximum particle count;
- minimum and maximum plotted-variable value;
- MLT day/night sector;
- explicit MLT interval, including intervals that wrap through midnight;
- WGS84 geographic latitude and longitude bounds;
- finite/valid orbit and magnetic-coordinate status;
- coordinate view: `geographic`, `magnetic`, or `footpoint`.

Time bounds are inclusive unless a configuration explicitly requests a strict
comparison. The legacy particle threshold (`counts > threshold`) and LP upper
threshold (`variable < threshold`) remain expressible exactly.

## Plot presentation controls

- output filename and title;
- colormap;
- marker size;
- width, height, and DPI;
- linear or log10 colour scaling;
- global or configured map extent;
- machine-readable record of applied filters, selected-point count, numeric
  range, output dimensions, and file size.

## Archive analysis recipes

Configuration profiles retain the old recipe families without copying their
code:

- all-data geographic, magnetic, and footpoint maps;
- particle count above 100 in all three coordinate views;
- MLT day and night maps in all three coordinate views;
- July 26–August 26 day/night analysis;
- storm, non-storm, pre-storm, post-storm, and selected-month intervals;
- plasma-temperature and both electron-density products for those intervals;
- weighted SAA day/night centroid and shift;
- timestamp/data-availability plots;
- optional SYM-H time-series plotting when its external source file is
  provided.

## Legacy inconsistencies resolved explicitly

The archive contains contradictory comments and implementation details. These
are not silently propagated:

- The implemented sector was day `[06, 18)` MLT and night its complement,
  while some comments claimed day `[09, 15)` and night `[21, 03)`. Both are
  supported as named/configurable sector definitions; the default preserves
  the implemented `[06, 18)` behaviour.
- Particle thresholds were strict lower bounds, while LP thresholds were
  strict upper bounds despite comments sometimes saying “greater than”. The
  new configuration names the comparison explicitly.
- Multiple old recipes wrote different plots to the same filename. New output
  names must be unique; accidental overwriting is not preserved.
- Interactive `plt.show()` calls and debug printouts are not part of the edge
  product. Headless PNG generation and structured metadata replace them.

Feature parity means preservation of scientific choices and products, not
preservation of duplicated code or known accidental behaviour.
