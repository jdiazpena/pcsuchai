# Plotting and filtering

Plots are headless PNG products. All scatter observations are rendered as
solid, filled circles. Geographic spacecraft and geographic footpoint views
include bundled Natural Earth continent polygons; they do not require Cartopy
or a network connection at runtime. Native magnetic-coordinate views do not
display geographic continents because that would mix coordinate systems.

## Core products

A run with a magnetic backend always produces:

1. particle count at the recomputed spacecraft geographic position;
2. particle count in the selected backend's native magnetic coordinates;
3. particle count at the model-mapped zero-kilometre geographic footpoint.

Each title and manifest record reports the number of rendered observations.

## Configuration profiles

Use a JSON profile to request any number of additional products without
editing Python code:

```bash
pcsuchai analyze \
  --orbit-backend astropy \
  --magnetic-backend aacgmv2 \
  --plot-config configs/plots/archive-full.json
```

`archive-full.json` restores the archive's full overview, day/night,
storm/non-storm, pre/post-storm, selected-month, plasma, density, centroid, and
time-availability recipe families. `saa-narrow-mlt.json` preserves the
alternative comments that defined day as MLT 09–15 and night as MLT 21–03.
`example-custom.json` demonstrates combined time, excluded-time, MLT,
geographic-region, count, style, and map-extent options.

Every profile contains a `plots` list. Important fields are:

- `name`: unique output basename;
- `plot_type`: `map` or `time_availability`;
- `variable`: any trusted measurement named below;
- `coordinate_view`: `geographic`, `magnetic`, or `footpoint`;
- `include_times` and `exclude_times`: lists of inclusive ISO-UTC intervals;
- `mlt_sector`: `day` or `night`, using configurable `day_mlt_start` and
  `day_mlt_end`;
- `mlt_intervals`: arbitrary half-open MLT intervals, including midnight wrap;
- `geographic_latitude_min/max` and `geographic_longitude_min/max`;
- `particle_gt/ge/lt/le` and `value_gt/ge/lt/le`;
- `scale`: `auto`, `linear`, or `log10`;
- `cmap`, `marker_size`, `width_px`, `height_px`, `dpi`, `title`, and `extent`;
- `calculate_centroid`: add a particle-weighted centroid using the exact plot
  mask.

Supported variables are `particle_count`, `plasma_temperature`,
`plasma_voltage`, `sweep_voltage`, `plasma_current`,
`electron_density_300k`, and `electron_density_3000k`. Automatic density
scaling rejects non-physical values at or below 1 and plots base-10 logarithms,
matching the useful archive behaviour.

Every option and the resulting point count, data range, dimensions, and file
size are copied into the run manifest. Unknown or misspelled options are fatal
instead of being silently ignored.

## Optional SYM-H plot

The archived OMNI reference series was copied unchanged into `data/external`.
Plot all records or an inclusive interval with:

```bash
pcsuchai plot-symh
pcsuchai plot-symh --start 2018-08-25T07:00:00Z --end 2018-08-29T00:00:00Z
```

This is external contextual data, not a Langmuir-probe measurement.
