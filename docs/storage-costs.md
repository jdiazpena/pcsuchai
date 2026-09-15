# Saved storage and retention costs

The experiment report now writes `storage-costs.jsonl.gz`: one unchanged saved
storage record for every started attempt, including warmups, failures and partial
jobs. Missing historical measurements remain missing. No records are pruned.

New attempts record the parent-side verified gzip call for each closed raw file:
original/compressed bytes, compressed-to-original ratio, and wall seconds including
hash verification and fsync. Empty source files have an unavailable ratio, not a
division by zero. Product sharing has its own wall timer. Both costs lie inside
the committed job cycle; do not add them again to that cycle. Compression inside
the scientific worker already lies inside worker/stage timings and is not counted
as parent compression. Setup, finalization and export remain separate costs.

Allocation is measured with `st_blocks * 512`, not file length. Newly retained
product backing inodes are counted once; existing shared products add no new
product blocks. Unique raw logs still consume space. Hard-link failures retain
the original files and record their allocation. Attributed file blocks exclude
directory/metadata allocation, later run-record/checkpoint writes and temporary
peak usage: they are a lower bound, not a capacity budget.
Python documents the 512-byte block convention and sparse-file distinction in
its [stat result reference](https://docs.python.org/3/library/os.html#os.stat_result.st_blocks).
Available bytes/inodes use the caller-available `f_bavail`/`f_favail` fields of
[statvfs](https://man7.org/linux/man-pages/man3/statvfs.3.html).

Every attempt also saves filesystem free bytes/inodes immediately before its
intent is committed and after retention. Their difference describes the **whole
filesystem** over that interval. It includes other activity and excludes later
commit/finalization writes. Negative differences remain negative, not zero.
They cannot establish that a future job consumes no storage.

The report separately inventories the current saved tree, including directories
and counting hard-linked inode blocks once. Imported allocation describes the
analysis filesystem, not the original Pi. This inventory never supplies target
free space to a forecast. Filesystem metadata, journaling, filesystem-native
compression and allocations outside the tree are not measured by this inventory.

## Conditional pilot forecast

A report always shows the largest observed same-cohort growth and availability.
For a conditional estimate, supply additional jobs per exact workload cohort and
explicit byte headroom:

```bash
python3 scripts/run_experiment.py report SAVED_EXPERIMENT_DIRECTORY \
  --output NEW_REPORT_DIRECTORY \
  --storage-planned-attempts ADDITIONAL_JOBS_PER_COHORT \
  --storage-reserve-bytes HEADROOM_BYTES
```

Replace all uppercase placeholders. The count includes warmups and failures,
not just successful jobs. This is a saved-record analysis command, not a launcher.
With several cohorts the supplied count applies separately to each; it is not a
combined storage budget for running all those cohorts together.

The estimate uses the largest observed whole-filesystem byte growth and inode
growth among all started same-workload attempts and the latest saved target free
bytes/inodes. It subtracts supplied byte headroom and takes the tighter byte/inode
limit. It never uses the current analysis PC's free space. Missing or negative
growth, zero observed growth, unavailable capacity or missing headroom makes the
forecast unavailable. An incomplete pilot is not silently reduced to successful
jobs. Old campaigns without these acquisition-time observations cannot provide
this forecast retrospectively.

`fits_observed_capacity` means only that the arithmetic projection fits those
saved observations. It is **not a guarantee** or a statistical upper bound. The
pilot may miss the largest job, temporary staging, later commit/setup/finalization
cost and future background allocations. Byte headroom must cover those unknowns;
the inode limit likewise does not establish a reserve for staging/commit inodes.
Saved capacity may be stale. Recheck bytes/inodes on the Pi before launching and
inspect a representative pilot there. Existing between-job safety checks remain
in place, but cannot guarantee that the next active job will fit. All recoverable
raw data remains retained if a campaign stops.
