# Canonical measurement input

The canonical SUCHAI-1 Langmuir-probe and particle-counter table is included
in this repository and release bundles, by the maintainer's explicit decision.

The pipeline reads:

```text
data/raw/langmuir-2018-2.csv
```

Its original bytes are preserved. The expected SHA-256 digest is recorded in
`configs/benchmark/input-manifest.json` so preflight rejects a changed input.
Existing geographic and classification columns are ignored and recalculated.
Data-provider terms are separate from the software's GPL license.
