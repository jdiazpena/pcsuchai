# Measurement data contract

The canonical source is a private, locally supplied
`data/raw/langmuir-2018-2.csv`. Its name and bytes are
preserved from the archive, but it is tab-separated rather than comma-separated.

## Trusted source products

The pipeline reads only `time`, `header`, `Particles counter`, `Plasma
temperature`, `Plasma voltage`, `Sweep voltage`, `Plasma current`, `Electron
density 300K`, and `Electron density 3000K`.

The source contains 26,725 observations between 2018-04-16 and 2018-09-27. Its
255 duplicate timestamps are preserved because no scientific justification for
discarding them has yet been established.

The trusted instrument fields are not all finite. The canonical file contains
126 positive-infinity plasma-current values and 172 positive-infinity values
in each electron-density channel. They are preserved as source products,
counted by the full validation certificate, and excluded only from operations
that require a finite numeric value. Particle count, temperature, voltage, and
sweep voltage are finite for all 26,725 rows.

## Ignored historical products

Existing longitude, latitude, day/night, anomaly, difference, group, and season
columns are ignored. Orbit position, magnetic coordinates, classifications,
and subsequent analyses are regenerated with documented code.
