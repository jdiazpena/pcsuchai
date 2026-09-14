# Raw data retention and storage

Summaries are additional products, not substitutes for acquired data. Gzip and
NPZ use lossless compression: no rounding, downsampling, duplicate removal or
replacement of NaN/infinity is performed. Compression requires only Python's
standard library and the already-required NumPy.

## Retained data

- The canonical `data/raw/langmuir-2018-2.csv` is included in Git and release
  bundles. Its original bytes and checksum are unchanged. `archive/` is ignored.
- Each campaign saves one gzip snapshot of every measurement, TLE, EOP and
  plot-profile input under `benchmark/inputs/`, with source and compressed
  checksums in `input-snapshots.json`. `source-snapshot.tar.gz` retains exactly
  the code/configuration files identified by the recorded source digest.
- Each complete analysis saves `raw-products-<backends>.npz`: all trusted
  instrument fields, timestamps, headers, source rows, TLE selection arrays,
  orbit arrays, magnetic/footpoint arrays, error codes and the three basic-map
  masks. Nonfinite values and duplicate timestamps are preserved.
- Each configured plot saves `<plot>.selection.npz`: the full source-row mask,
  full x/y/value arrays, labels and scale before rendering. The input recipe
  is recorded in the manifest/profile. These NPZ arrays align with the rows in
  `raw-products-<backends>.npz`; no scientific data are embedded only in PNGs.
- With benchmarking enabled, `benchmark-<backends>.samples.csv.gz` contains
  every acquired stage sample, including UTC/elapsed time, RSS, threads, RAM,
  swap, temperature, frequency, load, cumulative CPU/I/O/context-switch/fault
  counters, and sampling-error information. The requested period is 50 ms;
  actual timestamps show scheduling delays. Firmware throttling is polled at
  stage boundaries and in the slower system timeline, not every 50 ms. An
  empty metric is unavailable/not polled, never an invented zero.
- Each run retains complete stdout/stderr logs and its system samples in
  `stdout.log.gz`, `stderr.log.gz`, `system-telemetry.csv.gz`, plus its complete
  `run-record.json`. Failures and interrupted attempts retain partial products
  and logs too.
- The live campaign system timeline is `system-telemetry.csv`. On clean stop
  it becomes `system-telemetry.<segment-UTC>.csv.gz`. Resume appends a new live
  segment, retaining all previous compressed segments. UTC, segment IDs and
  cumulative elapsed time make resumes distinguishable. Events remain in the
  append-only `campaign-events.jsonl`.

Live stage rows are immediately flushed and fsynced at least once per second
and at stage end. Compression occurs after sampling closes; decompressed
SHA-256 is verified before replacing the plain file. An abruptly terminated
process can leave plain CSV/logs or a compression temporary file: keep these
as evidence. Power loss can lose unsynced data; no software promises absolute
durability against storage hardware failure.

## Repeated products without repeated disk consumption

Completed products are hashed and byte-identical files are hard-linked through
the campaign's `artifact-store/`. Each run still contains its own normal file
paths. Only exactly identical bytes share storage; changing numerical results
are always saved separately. Raw timed samples generally differ and are never
deduplicated merely because their values look similar.

Treat completed outputs as immutable. Editing a hard-linked file in place
would change every linked view. To edit a copy, copy it outside the campaign
first. Filesystems without hard links retain full copies instead; the run's
`storage.fallback_files` records that condition.

`run-record.json` reports logical product size, new backing-content bytes,
shared-file count and retention time. Compression/deduplication has overhead:
stage logging is inside measured stages; journal compression is inside the
whole child runtime; parent deduplication is outside child timing and separately
recorded. All devices must use the same retention implementation/settings.
Complete run records live on disk; session/checkpoint run entries reference
them rather than duplicating every stage record in growing campaign RAM.

On the Pi's Linux filesystem, use `du -sh outputs/benchmarks/pi5` and `df -h .`
to observe actual consumption. Do not add up each run's logical output size to
estimate physical use: identical products share storage. The 2 GB reserve guard
stops new measured runs, preserving all prior data; it does not guarantee that
26 GB will last an exact duration. Nothing is pruned to make room.

## Read and export

Read compressed samples directly, without expanding all runs:

```bash
gzip -cd PATH/benchmark-astropy-aacgmv2.samples.csv.gz | head
gzip -cd PATH/system-telemetry.SEGMENT.csv.gz | head
```

Read numeric archives without pickle:

```python
import numpy as np

with np.load("PATH/raw-products-astropy-aacgmv2.npz", allow_pickle=False) as data:
    current = data["measurement_plasma_current"]
    source_rows = data["measurement_source_rows"]
with np.load("PATH/plot-name.selection.npz", allow_pickle=False) as plot:
    selected_rows = source_rows[plot["mask"]]
    plotted_values = plot["values"][plot["mask"]]
```

To export complete campaign results while preserving shared files, archive the
whole device directory (including `artifact-store`) rather than SCP-copying
thousands of individual hard-linked files:

```bash
tar -czf pi5-results.tar.gz outputs/benchmarks/pi5
```

Tar records hard links; independent file-by-file copies may expand every link
and require much more storage. Exporting does not remove original results.
