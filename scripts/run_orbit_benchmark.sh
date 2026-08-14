#!/usr/bin/env bash
# Repeated clean-process orbit diagnostic. Official results use run_comparison.sh.
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STAMP=$(date -u '+%Y%m%dT%H%M%SZ')
DESTINATION="$ROOT_DIR/outputs/diagnostics/orbit-benchmark/$STAMP"
REPEATS=${1:-5}
LIMIT=${2:-}
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
COMMAND=(python3 -m pcsuchai benchmark-orbits --project-root "$ROOT_DIR" --output-dir "$DESTINATION" --repeats "$REPEATS")
if [[ -n "$LIMIT" ]]; then COMMAND+=(--limit "$LIMIT"); fi
mkdir -p "$DESTINATION"
"${COMMAND[@]}" 2>&1 | tee "$DESTINATION/console.log"
printf 'Repeated orbit diagnostic complete: %s\n' "$DESTINATION"
