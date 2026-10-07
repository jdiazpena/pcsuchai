# One-file final result package

After an experiment ends, export it as before. Then run one additional packaging
command. This does **not** rerun analysis, plots, validation or benchmarking.
It does not delete or rewrite any original result, export or operation log.

## On the Pi

Run these separately, using new output names:

```bash
python3 scripts/run_experiment.py export EXPERIMENT_DIRECTORY --output outputs/DEVICE-EXPERIMENT-export.tar.gz
```

After export finishes:

```bash
python3 scripts/run_experiment.py package outputs/DEVICE-EXPERIMENT-export.tar.gz --output outputs/DEVICE-EXPERIMENT-complete.tar
```

If the export already exists, **skip export** and run only `package`. It finds
the matching master-run/master-resume logs and completed export log in their
normal dated locations. Manifest and archive hashes bind them to this experiment;
missing/mismatched evidence is refused. All matching master sessions are included,
including unfinished receipts without inventing a terminal. Unrelated runs are
not mixed in.

```text
DEVICE-EXPERIMENT-complete.tar
├── experiment.tar.gz                 original export, byte-for-byte
├── operation-costs/master/<ID>/       matching run/resume logs
├── operation-costs/export/<ID>/       matching completed export log
└── package.json                      experiment identity + member hashes
```

The wrapper is an uncompressed `.tar`: the existing gzip, PNG and NPZ bytes are
already compressed. It avoids a second compression pass. Download **only this
final file**, saving its printed SHA-256:

```powershell
scp pi@PI_HOST:/home/pi/pcsuchai/outputs/DEVICE-EXPERIMENT-complete.tar .
```

It consumes roughly another copy of the original export plus the small logs;
ensure free space. No automatic pruning occurs. No new dependencies or reinstall
are needed after updating the source. Existing packages cannot be overwritten,
and active experiments cannot be packaged. A failed publication retains its new
`.partial` file for diagnosis, without removing original evidence.

## On the analysis PC

Place the single file in ignored `results/`, using new destinations:

```bash
python3 scripts/run_experiment.py import-package results/DEVICE-EXPERIMENT-complete.tar results/imported-DEVICE-EXPERIMENT --sha256 TRANSFER_SHA256
python3 scripts/run_experiment.py verify-import results/imported-DEVICE-EXPERIMENT/experiment --images
python3 scripts/run_experiment.py report results/imported-DEVICE-EXPERIMENT/experiment --output outputs/reports/DEVICE-EXPERIMENT
python3 scripts/run_experiment.py costs results/imported-DEVICE-EXPERIMENT/transfer/operation-costs --output outputs/reports/DEVICE-EXPERIMENT-costs
```

Import checks the entire wrapper inventory, hashes, inner experiment identity,
and every receipt's experiment/export association. It then uses the existing
verified experiment importer without editing original records. Original export/
logs are under `transfer/`; ready-to-review results are under `experiment/`.
Hash verification is not scientific acceptance. Legacy exports and `import`
remain supported unchanged.

For logs/archive already moved to another computer, supply their exact log
folders with repeated `--receipt-root` options when packaging. Association uses
archive bytes and recorded original experiment, not a copied filename. If
multiple export receipts match, narrow the search to the intended folder;
the tool does not guess or combine ambiguous logs.

## Packaging measurements

Master/export logs finish **before** this step, so they can be included together.
No new external packaging-receipt folder is created. `package.json` records
preparation/payload-copy wall and parent CPU cost. It explicitly excludes its own
metadata/trailer writing, verification and publication: an immutable file cannot
contain the measured cost of its own later completion. These are not scientific
job timings and must not be added to containing benchmark clocks.

Packaging does not change the source/runtime recorded by an older experiment,
nor rerun or recertify it against today's checkout. Preserve those identities
when reviewing historical results.

## Local verification — 2026-10-07

The complete local suite passed **589 tests**, zero failures/errors/skips,
in 302.62 seconds. XML/logs are retained under
`outputs/verification/final-package-tests-y71rWtF0/`. The 17 packaging tests
cover unchanged export/log bytes, no scientific rerun, missing/mismatched logs,
unrelated runs, resumed/unfinished logs, copied archive names, exclusive output,
digest checks, malicious/tampered archives, publication failure and live guards.

The actual earlier Pi 5 export and its transferred master/export logs were also
packaged and imported locally, without any new science execution. All 443 result
files, 152 images and both operation logs passed verification; original archive
and receipt files stayed byte-identical. The 147,936,738-byte compressed export
became a 147,957,760-byte final file: only **21,022 extra bytes** for logs,
metadata and tar overhead. Evidence:
`outputs/verification/20261007T192244.276603Z-native-final-package/verification.json`.
This is historical-file transfer verification, not a fresh Pi run or target
performance measurement. No Pi connection, installation or GitHub push occurred.
