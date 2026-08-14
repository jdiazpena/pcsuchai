# Orbit processing

## TLE selection

For every observation, the pipeline selects the TLE with the smallest absolute
epoch difference. Because this is retrospective post-processing, both earlier
and later TLEs are eligible. Exact ties choose the earlier TLE. The signed
offset is stored with every derived position; a negative offset means the TLE
epoch occurs after the observation.

## Backends

The Astropy path runs the standard SGP4 propagation model, yielding TEME
position and velocity, then transforms TEME to ITRS and WGS84 geodetic
coordinates. Automatic Earth-orientation downloads are disabled and the
repository's local `finals2000A.all` file is used.

The Skyfield path constructs an `EarthSatellite` from the same selected TLE and
uses built-in offline time tables. It obtains WGS84 latitude, longitude, and
ellipsoidal elevation through `geographic_position_of`. Using `subpoint_of`
would incorrectly return zero elevation and is covered by cross-backend tests.

Both paths ultimately use SGP4; they are alternative software and coordinate
conversion implementations, not independent physical orbit models.

## Validation and benchmark parity

Orbit propagation and magnetic conversion are consecutive stages of every
complete operational run. The focused orbit diagnostic exists to explain and
validate that stage; it is not a segmented satellite workload.

Run the complete timestamped orbit diagnostic with:

```bash
scripts/run_orbit_diagnostic.sh
```

For a fast five-observation check:

```bash
scripts/run_orbit_diagnostic.sh 5
```

Each diagnostic directory contains:

- `orbit-validation.json`: validity counts, propagation error distributions,
  latitude/longitude/altitude differences, surface and three-dimensional
  separation, explicit consistency criteria, TLE assignment summary, input
  hashes, and runtime versions;
- `orbit-benchmark.json`: the same CPU, memory, I/O, frequency, thermal, and
  throttling schema used by the magnetic diagnostic;
- `orbit-differences.csv`: one auditable row per observation with both backend
  positions, selected TLE epoch/offset, error codes, and spatial differences;
- `console.log`: the operator-visible result.

The consistency limits are 0.01° latitude, 0.01° wrapped longitude, 0.1 km
altitude, and zero unmatched-validity rows. These compare two implementations
of the same TLE/SGP4 calculation. Passing does not prove agreement with the
satellite's true orbit.

The direct equivalent without the master script is:

```bash
pcsuchai validate-orbits \
  --output outputs/orbit-validation.json \
  --benchmark-output outputs/orbit-benchmark.json \
  --differences-output outputs/orbit-differences.csv
```

The official performance result remains `scripts/run_comparison.sh DEVICE`,
where each Astropy/Skyfield and AACGMv2/ApexPy combination executes the entire
measurement → TLE → orbit → magnetic → analysis → plot pipeline in a clean
process. Focused orbit timings diagnose the propagation stage only.

The complete gate also validates all TLE checksums, satellite identity,
chronology, duplicates, SGP4-at-epoch execution, assignment age/coverage, a
Vallado/CelesTrak SGP4 reference vector, local EOP interpolation for every
observation, and hashes of Skyfield's bundled offline time data. Five
orbit-specific plots expose backend separation, temporal differences,
recomputed altitude, selected-TLE age, and difference distributions.

For repeated clean-process orbit diagnostics:

```bash
scripts/run_orbit_benchmark.sh 5
```

This randomizes Astropy/Skyfield order and reports repeat statistics and output
hashes. It is explicitly non-official; only a validated complete-code campaign
may be used for the Raspberry Pi result.
