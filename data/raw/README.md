# Private measurement input

The original SUCHAI-1 Langmuir-probe and particle-counter telemetry is not
distributed with this repository.

Authorized operators must place the canonical file at:

```text
data/raw/langmuir-2018-2.csv
```

The file is ignored by Git and excluded from release bundles. Its expected
SHA-256 digest remains in `configs/benchmark/input-manifest.json` so preflight
can reject the wrong dataset without publishing the dataset itself.
