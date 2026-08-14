#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (($# < 3)); then
    printf 'Usage: %s OUTPUT_DIR SESSION_JSON SESSION_JSON [SESSION_JSON ...]\n' "$0" >&2
    exit 2
fi
OUTPUT_DIR=$1
shift
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m pcsuchai compare-sessions --output-dir "$OUTPUT_DIR" "$@"
