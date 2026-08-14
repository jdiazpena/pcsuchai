#!/usr/bin/env bash
# Focused orbit correctness/performance diagnostic; not the official full workload.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAMP=$(date -u '+%Y%m%dT%H%M%SZ')
DESTINATION="$ROOT_DIR/outputs/diagnostics/orbit/$STAMP"
LIMIT=${1:-}
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
COMMAND=(python3 -m pcsuchai validate-orbits
  --output "$DESTINATION/orbit-validation.json"
  --benchmark-output "$DESTINATION/orbit-benchmark.json"
  --differences-output "$DESTINATION/orbit-differences.csv"
  --plots-output-dir "$DESTINATION/plots")
if [[ -n "$LIMIT" ]]; then COMMAND+=(--limit "$LIMIT"); fi
mkdir -p "$DESTINATION"
"${COMMAND[@]}" | tee "$DESTINATION/console.log"
printf 'Orbit diagnostic complete: %s\n' "$DESTINATION"
