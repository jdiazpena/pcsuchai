#!/usr/bin/env bash
# Focused magnetic correctness/performance diagnostic; not the official full workload.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAMP=$(date -u '+%Y%m%dT%H%M%SZ')
DESTINATION="$ROOT_DIR/outputs/diagnostics/magnetic/$STAMP"
ORBIT_BACKEND=${1:-astropy}
LIMIT=${2:-}
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
COMMAND=(python3 -m pcsuchai validate-magnetic
  --orbit-backend "$ORBIT_BACKEND"
  --output "$DESTINATION/magnetic-validation.json"
  --benchmark-output "$DESTINATION/magnetic-benchmark.json"
  --differences-output "$DESTINATION/magnetic-differences.csv")
if [[ -n "$LIMIT" ]]; then COMMAND+=(--limit "$LIMIT"); fi
mkdir -p "$DESTINATION"
"${COMMAND[@]}" | tee "$DESTINATION/console.log"
printf 'Magnetic diagnostic complete: %s\n' "$DESTINATION"
